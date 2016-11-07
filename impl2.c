/*
This module attempts to implement the following pseudocode.  This code extracts
phone numbers (and only valid phone numbers) from audio recordings.  The intent
is to extract only valid routing data from calls without running the risk of 
capturing content, both of which could be carried by DTMF tones.  In this way,
it functions as an automated "taint team", extracting data that can be legally
captured without allowing the government undue access to sensitive information
that should not be captured.

It makes the following assumptions:
1. non-DTMF content (voice) can act as the separator between content that is
   permissible to capture and that which isn't.  For example, this could be the
   separation between a user inputting a credit, subscriber or calling card
   number and the number the user is attempting to call
2. There is some amount of time after which dialing "times out".

Item 1 is the one more likely to act as a separator here.

while (audio is coming in):
	run Goertzel
	if DTMF detected and has been on longer than minimum time
		record DTMF symbol
		reset voice & silence timers
	else if voice detected and has been detected longer than the minimum time:
		record record separator
		reset DTMF timer
	else:
		reset DTMF & voice timers
		if silence has been on longer than minimum time:
			record record separator

For each recorded symbol:
	if there are no symbols in the potential number yet:
		and the digit is between 2 an 9:
			record symbol in potential number
		and this is the first digit we've looked at and it's a 1:
			skip to next symbol
		otherwise, empty potential buffer and read to the next record separator
	if there are less than 10 symbols in the potential number buffer:
		and the symbol we're examining is in the range 0-9:
			record symbol in potential buffer
		otherwise, empty potential buffer and read to next record separator
	if there are 10 symbol in the potential buffer:
		and the symbol under examination is a record separator or (the symbol 
				under examination is '#' and the next symbol is a record 
				separator):
			record the potential number as a detected number
		otherwise, empty potential buffer and read to the next record separator

Note that although this is presented here and implemented in this program as 
two distinct stages (parse audio, then parse symbols), there is nothing 
preventing both parts from being run at the same time.  That is, there is no
reason differentiation between valid envelope data and content data cannot
happen at the same time as the detection of DTMF symbols.

Goertzel Implementation based on text of 
http://www.embedded.com/design/configurable-systems/4024443/The-Goertzel-Algorithm
and verified against the sample output there.  There are slight rounding
mismatches, but nothing significant.

Using the following as the end of a gstreamer-1.0 pipeline will convert audio
into a format usable by this tool:
! audioconvert ! audioresample ! audio/x-raw, rate=8000, format=S8 ! \
  filesink location=file.raw
  
Compile as:  cc -g -D_XOPEN_SOURCE=700 -std=c99 -lm -o impl2 impl2.c
*/

#include <stdlib.h>
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <string.h>
#if _POSIX_C_SOURCE >= 2 || _XOPEN_SOURCE
#include <unistd.h>
#else
#error getopt not supported on this system
#endif
#if _SVID_SOURCE || _BSD_SOURCE || _POSIX_C_SOURCE >= 200809L || \
               _XOPEN_SOURCE >= 700
#include <strings.h>
#else
#error ffs() not supported on this system
#endif

#define SAMPLE int8_t

#define LOG_DEFAULT 0
#define LOG_VERBOSE 1
#define LOG_DEBUG	2
#define log(level, ...) if (log_level>=level) \
	fprintf(log_output_file, __VA_ARGS__);

uint8_t log_level = 0;
FILE *log_output_file;

#ifndef M_PI
#define M_PI (3.14159265358979323846)
#endif

// All times measured in msec
#define SAMPLE_RATE			8000	// Hz

#define N					205	//105 is minimum for DTMF detection
								//205 frequently used/standard
#define SAMPLE_LENGTH		((float)N/SAMPLE_RATE)*1000	//in msec

#define MAX_INTERDIGIT_TIME	10 * 1000	// milliseconds
#define MIN_DIGIT_ON_TIME	40	// milliseconds
#define MAX_DIGIT_INTERRUPT	10	// milliseconds
#define MIN_VOICE_ON_TIME	1*1000 - 0*SAMPLE_LENGTH	//milliseconds

#define THRESH_DTMF 10
#define THRESH_VOICE -23

// Coefficient (k) calculated from DTMF frequency via k=N(fi/fs), where:
//  N is the constant filter length
//  fi is the DTMF frequency
//  fs is the sampling frequency
#define k(freq)				(int)(0.5 + (( (float)N * freq ) / SAMPLE_RATE))
#define coeff(freq)			2*cos((2.0*M_PI*k(freq))/(float)N)

static float DTMF_TONES[8] = { 697, 770, 852, 941, 1209, 1336, 1477, 1633 };

/* The following encodes DTMF on/off state into a byte using the index of the
 * tone in DTMF_TONES
 */
#define TONESTATE	uint8_t
#define TONESET(a, t)	(a |= (1<<t))
#define TONECLEAR(a, t)	(a &= ~(1<<t))
#define TONEISSET(a, t) (a>>t & 1)

static char DTMF2CHAR[5][5] = {
	/* row    { none, 1209 , 1336, 1477, 1633 }, */
	/* none */ {' ', ' ', ' ', ' '},
	/* 697 */ {' ', '1', '2', '3', 'A'},
	/* 770 */ {' ', '4', '5', '6', 'B'},
	/* 852 */ {' ', '7', '8', '9', 'C'},
	/* 941 */ {' ', '*', '0', '#', 'D'},
};

// The base size of the symbol buffer - where it starts & how much it grows by
#define SYMBOL_BUFFER_UNIT_SIZE	100

// Used to keep track of symbols as they're detected for later processing
char *symbol_buffer;
int symbol_buffer_length = SYMBOL_BUFFER_UNIT_SIZE;
int symbol_buffer_used = 0;

/*
Convert a TONESTATE to the human-readable character-equivalent.
*/
char state_to_char(TONESTATE state)
{
	TONESTATE upper = state >> 4 & 0xF;
	TONESTATE lower = state & 0xF;

	return DTMF2CHAR[ffs(lower)][ffs(upper)];
}

/*
Convert the magnitude output of Goertzel into dBFS.  dBFS is decibels relative
to the max output (volume/voltage/whatever) without clipping.  Since we're in
digital-land, this is easy - the max number that can be stored in the space
used for a single (audio) sample (ie: 8 bits).
*/
float rms2db(float mag)
{
	//RMS power = 0.707 * Peak Power
	//All our measurements are relative to max RMS power
	return 20 * log10(fabs(mag) /
			  (powf(2, (sizeof(SAMPLE) * 8) - 1) * 0.707));
}

/*
Perform Goertzel algorithm on the specified set of N samples for the coefficient
passed in.
sqrt() is in there to scale the value back down to a reasonable range.
*/
float goertzel(SAMPLE * samples, float coeff)
{
	float Q1 = 0, Q2 = 0;
	for (int i = 0; i < N; i++) {
		// Copy variables for cycle
		float Q0 = coeff * Q1 - Q2 + (float)samples[i];
		Q2 = Q1;
		Q1 = Q0;
	}

	return sqrtf((Q1 * Q1 + Q2 * Q2 - Q1 * Q2 * coeff) / (N / 2));
}

#define VAD_DECAY_RATE	0.1
float rms_avg = 0;
/*
Compute RMS of a set of SAMPLEs, then updates the running average.  Returns 
true if there is sufficient activation to believe there could be voice
content.
*/
bool has_voice(SAMPLE * sample)
{
	float res = 0;
	for (int i = 0; i < N; i++) {
		res += sample[i] * sample[i];
	}
	rms_avg =
	    (VAD_DECAY_RATE) * sqrt(res / N) + rms_avg * (1 - VAD_DECAY_RATE);
	log(LOG_DEBUG, "RMS(sample): %f, RMS(avg):%f\n", sqrt(res / N),
	    rms_avg);
	log(LOG_DEBUG, "RMS dB: sample: %f, average: %f\n",
	    rms2db(sqrt(res / N)), rms2db(rms_avg));
	return (rms2db(rms_avg) > THRESH_VOICE);
}

/*
Wrapper around fread() to prevent partial reads from causing failure, if not at
EOF.
*/
bool read_file(SAMPLE * buffer, FILE * infile)
{
	int count = N;
	while (count > 0 && !feof(infile)) {
		count -= fread(buffer, sizeof(SAMPLE), count, infile);
	}
	if (count > 0) {
		if (feof(infile)) {
			return false;
		}
	}
	return true;
}

/*
Runs various tests to determine if the tone detection is genuine.  Detection
could also have been triggered by, for example, voice content.  This means
checking the first harmonic - this will be populated in voice, but not by
computer/mechanically generated tones.
*/
TONESTATE verify_tones(TONESTATE state, SAMPLE * buffer)
{
	for (int i = 0; i < 8; i++) {
		if (TONEISSET(state, i)) {
			if (rms2db(goertzel(buffer, coeff(DTMF_TONES[i] * 2))) >
			    THRESH_DTMF) {
				log(LOG_DEBUG,
				    "Clearing tone %f; found 1st harmonic\n",
				    DTMF_TONES[i]);
				TONECLEAR(state, i);
			}
		}
	}
	return state;
}

/*
Verifies that the tone results are a valid result (ie: are a DTMF tone).
*/
bool verify_state(TONESTATE state)
{
	log(LOG_DEBUG, "%s: input: 0x%2x\n", __func__, state);
	TONESTATE upper = state >> 4 & 0xF;
	TONESTATE lower = state & 0xF;
	log(LOG_DEBUG, "%s: upper: 0x%2x\n", __func__, upper);
	log(LOG_DEBUG, "%s: lower: 0x%2x\n", __func__, lower);
	// Check 1: Bits set in both upper and lower
	if (upper == 0 || lower == 0) {
		log(LOG_DEBUG,
		    "Rejected state; not tones in both upper & lower ranges\n");
		return false;
	}

	// Check 2: only one bit set in upper & lower
	TONECLEAR(upper, ffs(upper) - 1);
	TONECLEAR(lower, ffs(lower) - 1);
	log(LOG_DEBUG, "%s: upper: 0x%2x\n", __func__, upper);
	log(LOG_DEBUG, "%s: lower: 0x%2x\n", __func__, lower);

	if (upper != 0 || lower != 0) {
		log(LOG_DEBUG, "Rejected state; too many bits set\n");
		return false;
	}

	return true;
}

float on_time = 0;
float off_time = 0;
float voice_time = 0;
char on_char = '\0';
bool emitted = false;

/*
Manages printing of result chars so they only get printed once per instance.
*/
void emit(char x)
{
	if (!emitted) {
		if (log_level < LOG_VERBOSE || log_output_file != stdout) {
			printf("%c", x);
		}
		// Now symbol buffer stuff
		symbol_buffer[symbol_buffer_used] = x;
		symbol_buffer_used++;
		if (symbol_buffer_used >= symbol_buffer_length) {
			symbol_buffer = realloc(symbol_buffer,
						symbol_buffer_length +
						SYMBOL_BUFFER_UNIT_SIZE);
			memset(symbol_buffer + symbol_buffer_used, 0,
			       SYMBOL_BUFFER_UNIT_SIZE);
			symbol_buffer_length += SYMBOL_BUFFER_UNIT_SIZE;
		}
		emitted = true;
	}
}

/*
Resets printing result characters.  Prints timing information.
*/
void reset(void)
{
	if (emitted) {
		log(LOG_VERBOSE, "%c: Active: %f, silent: %f, voice: %f\n", 
			(on_char) ? on_char : '.', on_time, off_time, voice_time);
	}
	on_char = '\0';
	on_time = 0;
	off_time = 0;
	voice_time = 0;
	emitted = false;
}

/*
Called if the sample does not have a DTMF tone in it.  Resets, emits if long
enough apart we're sure the tone is done.
*/
void is_off(SAMPLE * buffer)
{
	if (has_voice(buffer)) {
		log(LOG_DEBUG, "Voice detected\n");
		voice_time += SAMPLE_LENGTH;
		log(LOG_DEBUG, "Voice on time: %f\n", voice_time);
		if (voice_time > MIN_VOICE_ON_TIME) {
			emit('.');
		}
	}
	off_time += SAMPLE_LENGTH;
	if (on_char != '\0' && off_time > MAX_DIGIT_INTERRUPT) {
		//Digit just timed out.
		emit(on_char);
		reset();
	}
	if (off_time > MAX_INTERDIGIT_TIME) {
		// Long off - separate inputs
		emit('.');
	}
}

/*
Called if the sample has a DTMF tone.  Manages emitting if the tone has been on
long enough.  Manages emitting if changing tones.
NB: The standard (Q.23 & Q.24) specifies a min. 40 ms break between tones.  Not
everyone implements this, so we do not force such a break.
*/
void is_on(char c)
{
	if (on_time == 0)
		reset();
	if (c != on_char && on_char != '\0') {
		emit(on_char);
		reset();
	}
	on_char = c;
	on_time += SAMPLE_LENGTH;
	if (on_time > MIN_DIGIT_ON_TIME)
		emit(on_char);
}

/* Stage 1 - filter audio into a symbol stream */
void stage1(FILE * infile)
{
	SAMPLE buffer[N];
	while (read_file(buffer, infile)) {
		TONESTATE state = 0;

		// For this set of samples, check each frequency
		for (int i = 0; i < 8; i++) {
			float res = goertzel(buffer, coeff(DTMF_TONES[i]));
			log(LOG_DEBUG, "%f, %.5f, %.5f\n", DTMF_TONES[i], res,
			    rms2db(res));
			if (rms2db(res) > THRESH_DTMF) {
				log(LOG_DEBUG, "Frequency %.1f detected\n",
				    DTMF_TONES[i]);
				TONESET(state, i);
			}
		}

		if (state) {
			// First tone filtering:
			state = verify_tones(state, buffer);
			// Second "logical filtering"
			if (verify_state(state)) {
				//Third, it's valid
				log(LOG_DEBUG, "Detected DTMF \"%c\"\n",
				    state_to_char(state));
				is_on(state_to_char(state));
			} else {
				is_off(buffer);
			}
		} else {
			is_off(buffer);
		}
	}
}

/*
Given a pointer to a string, this function operates on the string to determine
if it contains a valid NANP number.  When it returns, returns a pointer 
guaranteed to be pointing at either . or \0
*/
char *validate_num(char *buffer)
{
	char *start = buffer;
	char pot_num[15] = { 0 };
	int pos = 0;

	// While not at a separator
	while (*buffer != '.') {
		if (pos == 0 && start == buffer) {	//if we haven't examined any digits...
			if (*buffer == '1') {	// and we're looking at at 1
				buffer++;	//move to the next entry
				continue;	// and the next iteration
			} else if (*buffer >= '2' && *buffer <= '9') {	// and we're  
				// looking at something in the range 2-9
				pot_num[pos] = *buffer;	// record the entry
				pos++;
			} else {	// empty buffer and not 1 or 2-9 means invalid number
				break;	// Move to next possible number
			}
		} else if (pos == 0 && (*buffer == '1' || *buffer == '0')) {
			// NANP numbers may not start with 0 or 1 and this is not positioned
			// so it could be the long-distance 1.  Invalid number
			break;
		} else if (pos == 10 && *buffer == '#' && buffer[1] == '.') {
			// If we have 10 digits and are looking at a separator or a #
			// followed by a separator:
			buffer++;	// move on to the .
			break;
		} else {
			if (pos < 10 && *buffer >= '0' && *buffer <= '9') {
				// not the first pos and not a full 10 digits and looking at 0-9
				// -> add to buffer and move on
				pot_num[pos] = *buffer;
				pos++;
			} else {
				break;	// Fell through somehow.  Too many digits or one that 
				// isn't 0-9
			}
		}
		// Move to the next character
		buffer++;
	}

	if (pos == 10 && *buffer == '.') {
		pot_num[pos] = '\0';	//end of string
		printf("%s\n", pot_num);	// Print as a valid result
	}
	// If we got here, we're either ready to move on or need to read until
	// ready to move on
	while (*buffer != 0 && *buffer != '.') {
		buffer++;
	}
	return buffer;
}

/* Filter stage 2 - parse symbol stream for "acceptable" formats. */
void stage2(void)
{
	char *buffer = symbol_buffer;
	while (*buffer != '\0') {
		buffer = validate_num(buffer) + 1;
	}
}

/*
Main function (entry point) of the program.  Manages parsing command line 
options and very high level program flow.
*/
int main(int argc, char **argv)
{
	symbol_buffer = calloc(symbol_buffer_length, sizeof(char));
	log_output_file = stdout;
	char c;
	while ((c = getopt(argc, argv, "hdv2")) != -1) {
		switch (c) {
		case 'h':
			exit(0);
			break;
		case 'd':
			log_level = LOG_DEBUG;
			break;
		case 'v':
			log_level = LOG_VERBOSE;
			break;
		case '2':
			log_output_file = stderr;
			break;
		}
	}

	log(LOG_VERBOSE, "Starting with sample rate of %d hz, block size %d\n",
	    SAMPLE_RATE, N);
	log(LOG_VERBOSE, "Sample length is %fmsec\n", SAMPLE_LENGTH);

	FILE *infile;
	if (optind < argc) {
		log(LOG_VERBOSE, "Reading input file %s\n", argv[optind]);
		errno = 0;
		infile = fopen(argv[optind], "r");
		if (errno) {
			perror(NULL);
			exit(1);
		}
	} else {
		log(LOG_VERBOSE, "Using stdin %d\n", argc);
		infile = stdin;
	}

	// Stage 1 processing
	stage1(infile);

	// Make the symbol buffer end in a .
	reset();
	emit('.');
	printf("\n");		//Separate stage1 output from stage2

	//Stage 2 processing
	stage2();

	//cleanup
	free(symbol_buffer);
	if (infile != stdin)
		fclose(infile);
}
