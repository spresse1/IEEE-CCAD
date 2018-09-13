CCAD: The Call Contents Automatic Differentiator
================================================

This repository contains the code, test harness and paper that comprise 
CCAD, the Call Contents Automatic Differentiator.  It is designed to 
separate "content" from "metadata" in telephone calls.  Under the law, 
digits dialed during a phone call may be either content or non-content.  
Non-content is so-called "Dialing, Routing, Addressing and Signaling" 
(DRAS) information.  DRAS may legally be collected without a warrant, as 
it has no expectation of privacy.  DRAS may be embedded within a call 
if, for example, one calls an international dialing service.

Unfortunately, the same signaling method - DTMF (Dual-Tone 
Multi-Frequency), which is sent when you press a button on your 
telephone - is sometimes for content information, like bank 
account numbers, PINs, passwords or credit card information.

This codebase is intended to accompany the paper "Extracting Dialed 
Telephone Numbers from Unstructured Audio" presented at the 2018 IEEE 
International Symposium on Technologies for Homeland Security.

What's included
===============

This repository contains all CCAD related materials.  Namely:

* ccad.c - The program itself
* TestHarness.py - The program used to build and run tests of CCAD

Common tasks
============

We assume you are running on a POSIX-compliant machine with 
X_OPEN_SOURCE>=700.  Normally the determination of this would be handled 
by a Makefile, but one has not yet been written for this project.  Any 
modern Linux system should meet this requirement; other operating 
systems may vary.

Compilation
-----------

With a C compiler installed, compile by running:

    $ cc -g -D_XOPEN_SOURCE=700 -std=c99 -lm -o ccad ccad.c

Test Audio Creation
-------------------

The test harness requires input audio.  In the paper,  ITU-T 
Recommendation P.23's supplemental audio database is used.  This may be 
accessed online at [the ITU's 
website](https://www.itu.int/net/itu-t/sigdb/genaudio/AudioForm-g.aspx?val=1000023).  
It then needs to be transformed into a useable format (8-bit signed PCM 
audio).  This requires the installation of 
[gstreamer](https://gstreamer.freedesktop.org/) and 
[audacity](http://www.audacityteam.org/).

In order to voice files, run (may require some path changes):
```
# for FILE in $(find P_Suppl_23_DB/ -name "*.OUT" | \
awk -F. '{print $1}'); do gst-launch-1.0 filesrc location=${FILE}.OUT ! \
audioparse channels=1 rate=16000 raw-format=GST_AUDIO_FORMAT_S16LE ! \
audioconvert ! audioresample ! wavenc ! filesink \
location=TestAudio/Edited/VoiceWavs/$(basename ${FILE}).wav; done
```

Then, in audacity, run the following chain on the new *.wav 
files (expressed in ``command: 
parameters``):
```
TruncateSilence:  Db="-40 dB" Action=0 Minimum=0.100000 Truncate=0.000000 Compress=50.000000
Normalize:  ApplyGain=yes RemoveDcOffset=yes Level=0.000000 StereoIndependent=no
ExportWAV
```

Finally, run the following (again, paths may need munging):
```
# for FILE in $(find P_Suppl_23_DB -name "*.wav" | \
awk -F. '{print $1}'); do gst-launch-1.0 filesrc \
location=${FILE}.wav ! wavparse ! audioconvert ! audioresample ! \
audio/x-raw, rate=8000, format=S8 ! filesink \
location=P_Suppl_23_DB/$(basename ${FILE}).raw; done
```

Next, on to the noise file.  The paper only used 
P_Suppl_23_DB/Disk1/NOISE/WHITE.BGN as noise.  To transform it, run:
```
# gst-launch-1.0 filesrc location=P_Suppl_23_DB/Disk1/NOISE/WHITE.BGN ! \
audioparse channels=1 rate=16000 raw-format=GST_AUDIO_FORMAT_S16LE ! \
audioconvert ! audioresample ! audio/x-raw, rate=8000, format=S8 ! \
filesink location=P_Suppl_23_DB/Disk1/NOISE/WHITE.raw
```
