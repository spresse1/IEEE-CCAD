#! /usr/bin/env python3

# Program to make test suites for DTMF/voice detection.
# args: num_tests speech_dir noise_dir

from random import randint
from math import sin, pi
from struct import pack
from tempfile import NamedTemporaryFile
from os import stat
import sys

SAMPLE_RATE=8000
BITS=8 # TODO changing this doesn't quite work yet.
SIGNED=True
MIN_VOICE_ON_TIME=1000
MAX_INTERDIGIT_TIME=10 * 1000

#static char DTMF2CHAR[5][5] = {
#	/* row    { none, 1209 , 1336, 1477, 1633 },*/
#	/* none */ { ' ', ' ', ' ', ' ' },
#	/* 697 */ { ' ', '1', '2', '3', 'A' },
#	/* 770 */ { ' ', '4', '5', '6', 'B' },
#	/* 852 */ { ' ', '7', '8', '9', 'C' },
#	/* 941 */ { ' ', '*', '0', '#', 'D' },
#};
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

class DTMFTest:
	def __init__(self, speech_files, noise_files):
		self.speech_files = speech_files
		self.noise_files = noise_files
		self.string = ""
		self.running_non_dtmf=0
		self.running_voice = 0

	def create_testfile(self, number):
		self.file=open("test%d.raw" % number, 'wb')
		self.contentfile=open("test%d.contents" % number, 'wb')
		while True:
			#self.file = open("testfile.raw", 'wb')#NamedTemporaryFile()
			output = randint(1, 10);
			if (output<=1):
				name = self.file.name
				self.file.flush()
				self.file.close()
				return name
			elif (output<=5):
				self.create_dtmf()
			elif (output<=9):
				self.create_voice()
			else:
				self.create_noise()
			if self.running_non_dtmf>MAX_INTERDIGIT_TIME and \
				(not self.string  or \
				(self. string and self.string[-1]!=".")):
				# If on long enough to be voice content and previous output
				# wasn't also a separator:
				self.string+="."
			if self.running_voice>MIN_VOICE_ON_TIME and \
				self.string and self.string[-1]!=".":
				# If on long enough to be voice content and previous output
				# wasn't also a separator:
				self.string+="."
	
	def create_noise(self):
		self.running_voice=0
		file = self.noise_files[randint(0,len(self.noise_files)-1)]
		length = self.include_file_part(file)
		self.running_non_dtmf += length		
		self.contentfile.write("Noise: %dms of %s\n" % ( length , file))
	
	def create_voice(self):
		file = self.speech_files[randint(0,len(self.speech_files)-1)]
		length = self.include_file_part(file)
		self.running_voice += length
		self.running_non_dtmf += length
		
		self.contentfile.write("Voice: %dms of %s\n" % ( length , file))
	
	# Takes file name, returns ms audio included from that file
	def include_file_part(self, file):
		stats = stat(file)
		start = randint(0, stats.st_size)
		length = randint(0, stats.st_size-start)
		with open(file, 'r') as fileH:
			fileH.seek(start, 0)
			content = fileH.read(length)
			self.file.write(bytes(content))
		#TODO fix for different sample sizes
		return len(content) * 1000.0 / SAMPLE_RATE
			
	def create_dtmf(self):
		self.running_non_dtmf=0
		self.running_voice=0
		length = randint(1,16)
		while (length>0):
			length-=1
			digit = randint(0,15)
			time = randint(40,1000)
			interdigit_time = randint(40,1000)
			self.contentfile.write("DTMF: %dms silence\n" % interdigit_time)
			self.contentfile.write("DTMF: %s for %dms\n" %
				(TONES[digit][0], time))
			# 40-1000 ms of tone
			self.generate(time, TONES[digit][1], TONES[digit][2])
			# 40+ ms post-digit silence
			for i in range(0, int(interdigit_time/1000.0 * SAMPLE_RATE)):
				self.file.write(pack('b', 0)[0])
			self.string+=TONES[digit][0]
			self.running_non_dtmf += interdigit_time
	
	# Time in msec
	def generate(self, time, freq1, freq2):
		samples = int((time/1000.0) * SAMPLE_RATE)
		if (SIGNED):
			amp_max = (2**(BITS-1))-1
			amp_offset=0
			typestring='b'
		else:
			amp_max = 2**(BITS)-1
			amp_offset = int(amp_max/2)
			typestring='c'
			
		STEP = ((2 * pi)/SAMPLE_RATE)
		for i in range(0,samples-1):
			self.file.write(pack('i', 
				int(amp_offset + amp_max/2 * sin(freq1 * STEP * i) + \
				amp_max/2 * sin(freq2 * STEP * i))
				)[0])
		

if __name__ == "__main__":
	found_sep = False
	voice=[]
	noise=[]
	for file in sys.argv[1:]:
		if not found_sep and file!="--":
			#sys.stderr.write("Added %s to voice\n" % file)
			voice += [file]
		elif file=="--":
			#sys.stderr.write("Found separator\n")
			found_sep=True
		else:
			#sys.stderr.write("Added %s to noise\n" % file)
			noise += [file]
	print(voice)
	print(noise)
	if voice==[] or noise==[]:
		print("Must provide both voice and noise files. Separate with --")
		exit(1)
	test = DTMFTest(voice, noise)
	#test.create_dtmf()
	#test.create_voice()
	#test.create_noise()
	#test.file.close()
	print test.create_testfile(1)
	print test.string
