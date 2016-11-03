#! /usr/bin/env python

from random import randint
from math import sin, pi
from struct import pack
import sys
from os import stat, mkdir
import os.path
import subprocess
import multiprocessing

SAMPLE_RATE=8000
BITS=8
MIN_VOICE_ON_TIME=1000
MAX_INTERDIGIT_TIME=10 * 1000
INPUT_COMP_TIME=0

TONES= (
	("1", 697, 1209),
	("2", 697, 1336),
	("3", 697, 1477),
	("A", 697, 1633),
	("4", 770, 1209),
	("5", 770, 1336),
	("6", 770, 1477),
	("B", 770, 1633),
	("7", 852, 1209),
	("8", 852, 1336),
	("9", 852, 1477),
	("C", 852, 1633),
	("*", 941, 1209),
	("0", 941, 1336),
	("#", 941, 1477),
	("D", 941, 1633),
)

def samples2ms(samples):
	return samples * 1000.0 / SAMPLE_RATE

def ms2samples(ms):
	return int(ms / 1000.0 * SAMPLE_RATE)

class DTMFTest:	
	def __init__(self, voice_files, noise_files):
		self.voice = voice_files
		self.noise = noise_files
	
	def create_dtmf(self, outfile, contentfile, restrict=False, endinpound=False):
		length = randint(1,16)
		string=""
		while (length>0):
			length-=1
			digit = randint(0,15)
			time = randint(40,1000)
			interdigit_time = randint(40,1000)
			
			contentfile.write("DTMF: %s for %dms\n" %
				(TONES[digit][0], time))
			# 40-1000 ms of tone
			self.generate(outfile, time, TONES[digit][1], TONES[digit][2])
			# 40+ ms post-digit silence
			for i in range(0, ms2samples(interdigit_time)):
				outfile.write(pack('b', 0)[0])
			contentfile.write("DTMF: %dms silence\n" % interdigit_time)
			string+=TONES[digit][0]
		return (string, interdigit_time)

	# Time in msec
	def generate(self, outfile, time, freq1, freq2):
		samples = ms2samples(time)
		amp_max = (2**(BITS-1))-1
		amp_offset=0
		typestring='b'
		
		STEP = ((2 * pi)/SAMPLE_RATE)
		for i in range(0,samples-1):
			outfile.write(pack('i', 
				int(amp_offset + amp_max/2 * sin(freq1 * STEP * i) + \
				amp_max/2 * sin(freq2 * STEP * i))
				)[0])
		
	# Takes file name, returns ms audio included from that file
	def include_file_part(self, outfile, infile, start, length):
		#print("partial: start: %d, length %d" % (start, length))
		with open(infile, 'r') as fileH:
			fileH.seek(start, 0)
			content = fileH.read(length)
			outfile.write(bytes(content))
		#if len(content)!=length:
		#	print("requested file size %d, ended up putting in %d" % (length, len(content)))
		#TODO fix for different sample sizes
		return samples2ms(len(content))
	
	def make_segment(self, stype, files, previous_runtime, runtime_threshhold, outfile, contentfile):
		infile = files[randint(0,len(files)-1)]
		stats = stat(infile)
		start = randint(0, stats.st_size)
		length = randint(0, stats.st_size-start)
		if previous_runtime + samples2ms(length)>runtime_threshhold-INPUT_COMP_TIME and \
			previous_runtime + samples2ms(length)<runtime_threshhold+INPUT_COMP_TIME:
			# Remove 100ms audio. We do this because audio files may contain 
			# short silences.  These input errors cascade into significant 
			# errors in later tests. Set to exactly how much voice would be less than the 
			# window
			length = ms2samples((runtime_threshhold - INPUT_COMP_TIME) - previous_runtime)
			if length<=0:
				#Instead, set to how much to get past the window
				length = ms2samples((runtime_threshhold + INPUT_COMP_TIME) - previous_runtime)
			if start+length>stats.st_size:
				#insufficient wiggle room, skip
				return 0
		time = self.include_file_part(outfile, infile, start, length)
		contentfile.write("%s: %dms of %s\n" % ( stype, time , infile))
		contentfile.write("%s total: %dms\n" % ( stype, time + previous_runtime ))
		return time


	def make_file(self, outfilename, outverbose):
		running_non_dtmf=0.0
		running_voice=0.0
		string=""
		#with open(outfilename, 'wb') as outfile:
		#	with open(outverbose, 'w') as contentfile:
		outfile = open(outfilename, 'wb')
		contentfile = open(outverbose, 'w')
		while True:
			action = randint(0,12)
			if (action<=0):
				break
			elif (action<=4):
				out = self.create_dtmf(outfile, contentfile)
				string += out[0]
				running_voice=0.0
				running_non_dtmf=float(out[1])
			elif (action<=8):
				time = self.make_segment("Voice", self.voice, running_voice, MIN_VOICE_ON_TIME, outfile, contentfile)
				running_voice += time
				running_non_dtmf += time
			else:
				running_voice=0.0
				time = self.make_segment("Noise", self.noise, running_non_dtmf, MAX_INTERDIGIT_TIME, outfile, contentfile)
				running_non_dtmf += time
			if running_non_dtmf>MAX_INTERDIGIT_TIME and (not string or
				string[-1]!="."):
				# If on long enough to be voice content and previous output
				# wasn't also a separator:
				string+="."
			if running_voice>MIN_VOICE_ON_TIME and \
				(not string or string[-1]!="."):
				# If on long enough to be voice content and previous output
				# wasn't also a separator:
				string+="."
		outfile.close()
		contentfile.close()
	
		return string

class DTMFTestType2(DTMFTest):
	def make_file(self, outfilename, outverbose):
		string=""
		#with open(outfilename, 'wb') as outfile:
		#	with open(outverbose, 'w') as contentfile:
		outfile = open(outfilename, 'wb')
		contentfile = open(outverbose, 'w')
		while True:
			action = randint(0,10)
			if (action<=0):
				break
			else:
				out = self.create_dtmf(outfile, contentfile)
				string += out[0]
				time=0.0
				running_non_dtmf=float(out[1])
				if randint(0,1)==0:
					while time < MIN_VOICE_ON_TIME:
						time += self.make_segment("Voice", self.voice, time, MIN_VOICE_ON_TIME, outfile, contentfile)
				else:
					while time < MAX_INTERDIGIT_TIME:
						time += self.make_segment("Noise", self.noise, 
							time, MAX_INTERDIGIT_TIME, outfile, contentfile)
				if not string or string[-1]!=".":
					string+="."
		outfile.close()
		contentfile.close()
		return string

	def make_segment(self, stype, files, previous_runtime, runtime_threshhold, outfile, contentfile):
		infile = files[randint(0,len(files)-1)]
		stats = stat(infile)
		start = randint(0, stats.st_size)
		length = randint(0, stats.st_size-start)
		if previous_runtime + samples2ms(length)>runtime_threshhold-INPUT_COMP_TIME and \
			previous_runtime + samples2ms(length)<runtime_threshhold+INPUT_COMP_TIME:
			return 0
		time = self.include_file_part(outfile, infile, start, length)
		contentfile.write("%s: %dms of %s\n" % ( stype, time , infile))
		contentfile.write("%s total: %dms\n" % ( stype, time + previous_runtime ))
		return time	

BINFILE="./impl2"
	
def call_test_bin(outdir, testpath, infile, expected):
	errfile = open(testpath + ".output", 'w')
	res = subprocess.Popen( [ str(BINFILE), "-v", "-2", str(infile) ], 
		stdout=subprocess.PIPE, stderr=errfile)
	res.wait()
	output = res.stdout.read().strip()
	errfile.write("Expected: %s\n" % expected)
	errfile.write("Got:      %s\n" % output)
	errfile.flush()
	errfile.close()
	if res.returncode!=0:
		print "Processes under test returned non-zero code %d" % res.returncode
		print res.output
		exit(1)
	return output==expected

def single_test(inputdata):
	(testnum, voice, noise) = inputdata
	testgen = DTMFTest(voice, noise)
	testpath = os.path.join(outdir, "test%d" % testnum)
	knownres = testgen.make_file(testpath + ".raw", testpath + ".content")
	if call_test_bin(outdir, testpath, testpath+".raw", knownres):
		return True
	else:
		return testnum

def single_test_type2(inputdata):
	(testnum, voice, noise) = inputdata
	testgen = DTMFTestType2(voice, noise)
	testpath = os.path.join(outdir, "testt2%d" % testnum)
	knownres = testgen.make_file(testpath + ".raw", testpath + ".content")
	if call_test_bin(outdir, testpath, testpath+".raw", knownres):
		return True
	else:
		return testnum

if __name__=="__main__":
	found_sep=False
	voice=[]
	noise=[]
	outdir = sys.argv[1]
	count = int(sys.argv[2])
	for file in sys.argv[3:]:
		if not found_sep and file!="--":
			#sys.stderr.write("Added %s to voice\n" % file)
			voice += [file]
		elif file=="--":
			#sys.stderr.write("Found separator\n")
			found_sep=True
		else:
			#sys.stderr.write("Added %s to noise\n" % file)
			noise += [file]
	if voice==[] or noise==[]:
		print("Must provide both voice and noise files. Separate with --")
		exit(1)

	print(voice)
	print(noise)

	try:
		mkdir(outdir)
		print "Created output directory " + outdir
	except OSError:
		print "Output directory " + outdir + " exists"
		
	successes=0
	failed=[]
	pool = multiprocessing.Pool()
	res = pool.map(single_test, [(x, voice, noise) for x in range(count)])
	for i in res:
		if i is True:
			successes+=1
		else:
			#print i
			failed += [ i ]
	print "Type 1 test: %d/%d tests passed (%.1f%%)" % (successes, count, 
		(float(successes)/count)*100.0)
	print "Failed tests are:"
	print failed
	
	# Now do type 2 tests
	successes=0
	failed=[]
	pool = multiprocessing.Pool()
	res = pool.map(single_test_type2, [(x, voice, noise) for x in range(count)])
	for i in res:
		if i is True:
			successes+=1
		else:
			#print i
			failed += [ i ]
	print "Type 2 test: %d/%d tests passed (%.1f%%)" % (successes, count, 
		(float(successes)/count)*100.0)
	print "Failed tests are:"
	print failed
