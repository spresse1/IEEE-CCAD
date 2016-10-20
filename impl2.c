/*
This module attempts to implement the following pseudocode.  Thsi code extracts
phone numbers (and only valid phone numbers) from audio recordings.  The intent
is to extract only valid routing data from calls without running the risk of 
capturing content, both of which could be carried by DTMF tones.  In this way,
it functions as an automated "taint team", extracting data that can be legally
captured without allowing the government undue access to sensitive information
that should not be captured.

It makes the following assumptions:
1. non-DTMF content (voice) can act as the separator between content that is
   permissible to capture and that which isnt.  For example, this could be the
   separation between a user inputting a credit, subscriber or calling card
   number and the number the user is attempting to call
2. There is some amount of time after which dialing "times out".

Item 1 is the one more likely to act as a separator here.

array freq_samples
silence_time=0
for each sample:
	break info frequency bins
	all_bins_empty=True
	for each bin:
		if bin_value is greater than detection threshold and no voice in sample:
			all_bins_empty=false
			silence_time=0
			freq_samples[bin]=MAX_ABSENT_SAMPLES
		if bin_value is less than detection_threshold and freq_samples[bin]>0:
			freq_saomples[bin]--;
		if freq_samples[bin] is zero:
			store dtmf digit represented by bin
	if all_bins_empty:
		silence_time++;
	if silence_time is greater than maximum silence time or sample contains voice:
		if stored numbers are valid phone:
			print stored numbers
		wipe number store

Goertzel Implementaiton based on text of 
http://www.embedded.com/design/configurable-systems/4024443/The-Goertzel-Algorithm
and verified against the sample output there.  There are slight rounding
mismatches, but nothing significant.
*/

#include <stdlib.h>
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include <errno.h>

// All times measured in msec
#define SAMPLE_RATE			8000 // Hz
#define MAX_INTERDIGIT_TIME	10 * 1000 // milliseconds
#define MIN_DIGIT_ON_TIME	40 // milliseconds
#define MAX_DIGIT_INTERRUPT	10 // milliseconds

#define ROW_FREQS			{1208, 1336, 1477, 1633}
#define COL_FREQS			{697,  770,  852,  941 }
#define MAX_ERROR			0.018 // 1.8%

#define N					136	//105 is minimum for DTMF detection
								//205 used by example implementation
#define SAMPLE_LENGTH		N/(SAMPLE_RATE*1000) //in msec

// Coefficent (k) calculated from DTMF frequency via k=N(fi/fs), where:
//  N is the constant filter length
//  fi is the dtmf frequency
//  fs is the sampling frequency
#define k(freq)				(int)(0.5 + (( (float)N * freq ) / SAMPLE_RATE))
#define coeff(freq)			2*cos((2.0*M_PI*k(freq))/(float)N)

#ifndef M_PI
#define M_PI (3.14159265358979323846)
#endif

int stored_digits[15] = {0}; // Max length for a regulation phone number is 15
int stored_digit_count = 0;

#define SAMPLE int8_t

float goertzel(SAMPLE *samples, float coeff) {
	float Q1=0,Q2=0;
	for (int i=0; i<N; i++) {
		// Copy variables for cycle
		float Q0=coeff * Q1 - Q2 + (float)samples[i];
		Q2=Q1;
		Q1=Q0;
	}
	
	return Q1*Q1 + Q2*Q2-Q1*Q2*coeff;
}

void Generate(float frequency, SAMPLE *buffer)
{
  int	index;
  float	step;

  step = frequency * ((2.0 * M_PI) / SAMPLE_RATE);

  /* Generate the test data */
  for (index = 0; index < N; index++)
  {
    buffer[index] = (SAMPLE) (127.0 * sin(index * step));
  }
}

float mag2db(float mag) {
	return 20 * log10(fabs(mag)/32768);
}

int main(int argc, char **argv) {
	printf("Starting with sample rate of %d hz, block size %d\n", SAMPLE_RATE, N);
	printf("k for 941 is %d, Coeff for 941 is %f\n", k(941), coeff(941));
	SAMPLE buffer[N];
	
	FILE *infile;
	if (argc==2) {
		printf("readin file %s\n", argv[1]);
		errno=0;
		infile=fopen(argv[1], "r");
		if (errno) {
			perror(NULL);
			exit(1);
		}
	} else {
		printf("Using stdin %d\n", argc);
		infile=stdin;
	}
	
	fread(buffer, sizeof(SAMPLE), N, infile);
	for (float i=296; i<=3400; i=i+60) {
		float res = goertzel(buffer, coeff(i));
	
		printf("%f, %.5f, %.5f\n",i, res, mag2db(res));
	}
}
