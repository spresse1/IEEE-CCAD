#! /usr/bin/env python

from random import randint, seed
from math import sin, pi
from struct import pack
import sys
import re
from os import stat, makedirs
import os.path
import subprocess
import multiprocessing

SAMPLE_RATE = 8000
BITS = 8
MIN_VOICE_ON_TIME = 1000
MAX_INTERDIGIT_TIME = 10 * 1000
INPUT_COMP_TIME = 0

VALID_NUMBER_RE = re.compile("^[1]{0,1}([2-9][0-9]{9})[#]{0,1}$")

TONES = (
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

    def __init__(self, voice_files, noise_files, restrict=False,
                 endpound=False):
        self.voice = voice_files
        self.noise = noise_files
        self.restrict = restrict
        self.endpound = endpound

    def create_dtmf(self, outfile, contentfile):
        length = randint(1, 17)
        string = ""
        while (length > 0):
            length -= 1
            digit = randint(0, 15)
            while self.restrict and digit in [3, 7, 11, 12, 14, 15]:
                digit = randint(0, 15)
            if length == 0 and self.endpound and randint(0, 1) == 1:
                digit = 14  # pound
            time = randint(40, 1000)
            interdigit_time = randint(40, 1000)

            contentfile.write("DTMF: %s for %dms\n" %
                              (TONES[digit][0], time))
            # 40-1000 ms of tone
            self.generate(outfile, time, TONES[digit][1], TONES[digit][2])
            # 40+ ms post-digit silence
            for i in range(0, ms2samples(interdigit_time)):
                outfile.write(pack('b', 0)[0])
            contentfile.write("DTMF: %dms silence\n" % interdigit_time)
            string += TONES[digit][0]
        return (string, interdigit_time)

    # Time in msec
    def generate(self, outfile, time, freq1, freq2):
        samples = ms2samples(time)
        amp_max = (2 ** (BITS - 1)) - 1
        amp_offset = 0
        typestring = 'b'

        STEP = ((2 * pi) / SAMPLE_RATE)
        for i in range(0, samples - 1):
            outfile.write(pack(
                'i', int(amp_offset + amp_max / 2 * sin(freq1 * STEP * i) +
                         amp_max / 2 * sin(freq2 * STEP * i)))[0])

    # Takes file name, returns ms audio included from that file
    def include_file_part(self, outfile, infile, start, length):
        with open(infile, 'r') as fileH:
            fileH.seek(start, 0)
            content = fileH.read(length)
            outfile.write(bytes(content))
        return samples2ms(len(content))

    def make_segment(self, stype, files, previous_runtime, runtime_threshhold,
                     outfile, contentfile):
        infile = files[randint(0, len(files) - 1)]
        stats = stat(infile)
        start = 0 #randint(0, stats.st_size)
        length = randint(0, stats.st_size - start)
        if previous_runtime + samples2ms(length) > runtime_threshhold - \
            INPUT_COMP_TIME and previous_runtime + samples2ms(length) < \
                runtime_threshhold + INPUT_COMP_TIME:
            # Remove INPUT_COM_TIMEms audio. We do this because audio files may
            # contain short silences.  These input errors cascade into
            # significant errors in later tests. Set to exactly how much voice
            # would be less than the window
            length = ms2samples(
                (runtime_threshhold - INPUT_COMP_TIME) - previous_runtime)
            if length <= 0:  # If the starting sample was shorter than
                # INPUT_COMP_TIME Instead, set to how much to exceed window
                length = ms2samples(
                    (runtime_threshhold + INPUT_COMP_TIME) - previous_runtime)
            if start + length > stats.st_size:
                # insufficient wiggle room, skip
                return 0
        time = self.include_file_part(outfile, infile, start, length)
        contentfile.write("%s: %dms of %s\n" % (stype, time, infile))
        contentfile.write("%s total: %dms\n" %
                          (stype, time + previous_runtime))
        return time

    def make_file(self, outfilename, outverbose):
        running_non_dtmf = 0.0
        running_voice = 0.0
        string = ""
        outfile = open(outfilename, 'wb')
        contentfile = open(outverbose, 'w')
        while True:
            action = randint(0, 12)
            if (action <= 0):
                break
            elif (action <= 4):
                out = self.create_dtmf(outfile, contentfile)
                string += out[0]
                running_voice = 0.0
                running_non_dtmf = float(out[1])
            elif (action <= 8):
                time = self.make_segment(
                    "Voice", self.voice, running_voice, MIN_VOICE_ON_TIME,
                    outfile, contentfile)
                running_voice += time
                running_non_dtmf += time
            else:
                running_voice = 0.0
                time = self.make_segment(
                    "Noise", self.noise, running_non_dtmf, MAX_INTERDIGIT_TIME,
                    outfile, contentfile)
                running_non_dtmf += time
            if running_non_dtmf > MAX_INTERDIGIT_TIME and (not string or
                                                           string[-1] != "."):
                # If on long enough to be voice content and previous output
                # wasn't also a separator:
                string += "."
            if running_voice > MIN_VOICE_ON_TIME and \
                    (not string or string[-1] != "."):
                # If on long enough to be voice content and previous output
                # wasn't also a separator:
                string += "."
        string += "."
        contentfile.write("Symbol stream is: %s\n" % (string))
        outfile.close()
        contentfile.close()

        return string


class DTMFTestType2(DTMFTest):

    def make_file(self, outfilename, outverbose):
        string = ""
        outfile = open(outfilename, 'wb')
        contentfile = open(outverbose, 'w')
        while True:
            action = randint(0, 10)
            if (action <= 0):
                break
            else:
                out = self.create_dtmf(outfile, contentfile)
                string += out[0]
                time = 0.0
                running_non_dtmf = float(out[1])
                if randint(0, 1) == 0:
                    while time < MIN_VOICE_ON_TIME:
                        time += self.make_segment(
                            "Voice", self.voice, time, MIN_VOICE_ON_TIME,
                            outfile, contentfile)
                else:
                    while time < MAX_INTERDIGIT_TIME:
                        time += self.make_segment("Noise", self.noise,
                                                  time, MAX_INTERDIGIT_TIME,
                                                  outfile, contentfile)
                if not string or string[-1] != ".":
                    string += "."
        string += "."
        contentfile.write("Symbol stream is: %s\n" % (string))
        outfile.close()
        contentfile.close()
        return string

    def make_segment(self, stype, files, previous_runtime, runtime_threshhold,
                     outfile, contentfile):
        infile = files[randint(0, len(files) - 1)]
        stats = stat(infile)
        start = 0 #randint(0, stats.st_size)
        length = randint(0, stats.st_size - start)
        if previous_runtime + samples2ms(length) > runtime_threshhold - \
            INPUT_COMP_TIME and previous_runtime + samples2ms(length) < \
                runtime_threshhold + INPUT_COMP_TIME:
            return 0
        time = self.include_file_part(outfile, infile, start, length)
        contentfile.write("%s: %dms of %s\n" % (stype, time, infile))
        contentfile.write("%s total: %dms\n" %
                          (stype, time + previous_runtime))
        return time

BINFILE = "./impl2"


def call_test_bin(infile, errfile):
    res = subprocess.Popen([str(BINFILE), "-v", "-2", str(infile)],
                           stdout=subprocess.PIPE, stderr=errfile)
    res.wait()
    output = res.stdout.read().strip()
    if res.returncode != 0:
        print "Processes under test returned non-zero code %d" % res.returncode
        print res.output
        exit(1)
    return output


def single_test_type1(inputdata):
    (testnum, voice, noise) = inputdata
    seed(testnum)
    testgen = DTMFTest(voice, noise)
    testpath = os.path.join(outdir, "type1", "test%d" % testnum)
    knownres = testgen.make_file(testpath + ".raw", testpath + ".content")
    errfile = open(testpath + ".output", 'w')
    res = call_test_bin(testpath + ".raw", errfile)
    errfile.write("Expected: %s\n" % knownres)
    errfile.write("Got:      %s\n" % res)
    errfile.flush()
    errfile.close()
    if res.split("\n")[0] == knownres:
        return True
    else:
        return testnum


def single_test_type2(inputdata):
    (testnum, voice, noise) = inputdata
    seed(testnum)
    testgen = DTMFTestType2(voice, noise, restrict=True, endpound=True)
    testpath = os.path.join(outdir, "type2", "test%d" % testnum)
    symstream = testgen.make_file(testpath + ".raw", testpath + ".content")
    knownres = [VALID_NUMBER_RE.match(x).group(1) for x in symstream.split(".")
                if VALID_NUMBER_RE.match(x)]  # Gets only valid numbers
    errfile = open(testpath + ".output", 'w')
    res = call_test_bin(testpath + ".raw", errfile).split("\n")
    outsym = res[0]
    res = res[1:]
    res.sort()
    knownres.sort()
    errfile.write("Symstream: %s\n" % symstream)
    errfile.write("As read:   %s\n" % outsym)
    errfile.write("Expected: %s\n" % knownres)
    errfile.write("Got:      %s\n" % res)
    errfile.flush()
    errfile.close()
    if res == knownres:
        return True
    else:
        return testnum

if __name__ == "__main__":
    found_sep = False
    voice = []
    noise = []
    outdir = sys.argv[1]
    ttype = sys.argv[2]
    count = int(sys.argv[3])
    for file in sys.argv[4:]:
        if not found_sep and file != "--":
            voice += [file]
        elif file == "--":
            found_sep = True
        else:
            noise += [file]
    if voice == [] or noise == []:
        print("Must provide both voice and noise files. Separate with --")
        exit(1)

    if ttype not in ["1", "2", "both"]:
        print "Test type must be one of 1, 2, or both"
        exit(1)

    #print(voice)
    #print(noise)

    successes = 0
    failed = []
    pool = multiprocessing.Pool()

    if ttype == "1" or ttype == "both":
        newdir = os.path.join(outdir, "type1")
        try:
            makedirs(newdir)
            print "Created output directory " + newdir
        except OSError:
            print "Output directory " + newdir + " exists"

        res = pool.map(single_test_type1, [
                       (x, voice, noise) for x in range(count)])
        for i in res:
            if i is True:
                successes += 1
            else:
                failed += [i]
        print "Type 1 test: %d/%d tests passed (%.1f%%)" % (
            successes, count, (float(successes) / count) * 100.0)
        print "Failed tests are:"
        print failed

    if ttype == "2" or ttype == "both":
        newdir = os.path.join(outdir, "type2")
        try:
            makedirs(newdir)
            print "Created output directory " + newdir
        except OSError:
            print "Output directory " + newdir + " exists"

        # Now do type 2 tests
        successes = 0
        failed = []
        pool = multiprocessing.Pool()
        res = pool.map(single_test_type2, [
                       (x, voice, noise) for x in range(count)])
        for i in res:
            if i is True:
                successes += 1
            else:
                # print i
                failed += [i]
        print "Type 2 test: %d/%d tests passed (%.1f%%)" % (
            successes, count, (float(successes) / count) * 100.0)
        print "Failed tests are:"
        print failed
