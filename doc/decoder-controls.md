Decoder controls and first hardware tests
========================================

Source implementation; no hardware validation yet. No installer was built.
The private chart is deliberately unstarred for the user to assess.

Press d, then c for CW or r for RTTY. This starts capture if the selected
mode and input are usable. Only one capture runs. q leaves each menu with
Back and preserves capture; e inside explicitly stops or restarts it.
YAC exit stops capture and restores native decoder/Auto Information settings.
Native TS-590SG and IC-705 receiver settings are checked on readback.
A restoration failure is reported, rather than silently claimed successful.

v reviews the latest received text; comma moves backwards, full stop forwards
in 60-character chunks; n clears text. History is limited to 10,000 characters.
New decoded text appears automatically only while the decoder view is open;
elsewhere capture continues quietly. Terminal output uses existing screen
reader and braille support. There is no separate speech engine or guaranteed
speech queue policy. Decoding mistakes are expected in poor conditions.

TS-590SG CW
------------
Select CW or CW-R first. d c uses CD01 and nonpersistent AI2 only when AI
was Off. Existing AI2/AI4 is retained. CD2 characters are collected in a
background serial reader; all normal CAT exchanges use the same lock and
preserve fragmented unsolicited characters. Plus/minus adjust the native
threshold 1-30. No receiving-speed setting is needed; the radio tracks it.
Initial physical checks: decoder enable reply, streamed characters, tuning
while capture runs, threshold readback, Back leaving capture active, e stopping,
and original CD0/AI values restored on stop/exit. The Kenwood command guide
contains apparent CD0 answer/read formatting typos; YAC expects CD0 replies
and will fail safely if the real radio disagrees.

Audio CW: FTX-1, IC-705 and other supported radios
-------------------------------------------------
Carl's FTX1Remote CWReceiver uses audio and CWKit, not CAT decoded text.
The adaptive Morse timing here is a Python adaptation of CWKit's classic
MorseDecoder by Carl Obermeier. Full MIT notice: CWKit-LICENSE.txt.
Sources inspected:
https://github.com/captobie/ftx1-remote/blob/main/Sources/FTX1CW/CWReceiver.swift
https://github.com/captobie/cwdecode/blob/main/Sources/CWKit/Morse/MorseDecoder.swift

YAC's simpler fixed-tone detector is experimental. It does not include
CWKit's automatic frequency search, Apple Core ML model or its complete DSP
pipeline. Match the audio pitch to the incoming station. Timing follows
automatically from an initial speed estimate (default 20 WPM).

For a source installation, install the optional audio dependency in YAC's
Python environment:
    python -m pip install -r requirements-decoders.txt
Linux may also need its PortAudio runtime (Debian: libportaudio2).
List available inputs in that same environment:
    python -m sounddevice
Set these [yac] values in yac.ini:
    cw_audio_device = exact radio input name or numeric index
    cw_audio_channel = 1
    cw_audio_pitch_hz = 600
    cw_audio_threshold = 0.01
    cw_audio_wpm = 20

No default microphone is opened. Audio is requested at 48 kHz float32 and
converted to 8 kHz for detection. If the device does not accept 48 kHz,
start fails. Channel is a physical audio channel, not guaranteed Main/Sub;
check it after swapping receivers. cw_audio_threshold is a normalized RMS
level between 0 and 1. Initial WPM accepts 5-60; pitch accepts 200-1500 Hz.
No audio is recorded to disk or sent over the network. Decode pauses on TX,
non-CW mode or unknown radio TX state at periodic CAT checks. This polling
can lag and the first fraction of sidetone may enter the decoder. The native
TS-590SG path uses its radio decoder instead of audio.

Windows packaged audio capture needs sounddevice/PortAudio in the build
environment; installing a Python package beside an existing frozen executable
will not add it. Source and native CAT/RTTY capture do not need sounddevice.
No optional dependencies were installed or audio device opened in development.

IC-705 native RTTY
------------------
Select RTTY or RTTY-R first. d r identifies the unique companion USB interface
using the same USB physical identity as the connected CAT port. It does not
probe random ports. If necessary set [yac] rtty_port to the verified B device;
this override still must match the radio's USB identity. Missing or ambiguous
metadata is reported as setup failure, not guessed by adjacent COM numbers.
USB B opens with RTS and DTR deasserted. Any USB B SEND/CW/RTTY keying
assignment is refused before opening. DV Data/Weather functions are refused.
USB (B) Function changes from Off to RTTY Decode with acknowledgement/readback,
and its prior setting is restored when stopped. Port A remains CI-V.
Text is received only; no bytes are sent through B. The virtual USB stream
is opened at 9600 baud; practical byte formatting/driver behaviour still needs
checking with the radio. Only this native RTTY model is implemented so far.

Icom references: Basic Manual page 8-16; CI-V 1A 05 01 25/26/27 keying
assignments and 1A 05 01 33 USB B function.
https://www.icomeurope.com/wp-content/uploads/2024/06/IC-705_ENG_IM_Basic_7.pdf
https://www.icomeurope.com/wp-content/uploads/2020/08/IC-705_ENG_CI-V_1_20200721.pdf
Kenwood reference:
https://www.kenwood.com/i/products/info/amateur/pdf/ts590_g_pc_command_e_rev2.pdf

Start failures show concise translated guidance; detailed diagnostics use the
YAC log. No decoder commands set PTT, operating frequency, mode or RF power.

Guided receive audio setup
-------------------------
Use d a after installing the optional audio dependency. Full stop/comma browse
input devices, c selects a physical channel, v measures one second of audio,
e validates 48 kHz float32 support and saves the choice, q returns without
saving the current browsing choice. h gives translated help. No playback
stream is opened, no system defaults are changed, no audio is played or saved.
Setup stops existing audio CW capture so the level check can open that input;
restart capture explicitly. Native CAT CW/RTTY capture is not stopped.
The device list is enumerated without opening each candidate. Only v opens
an input, explicitly on request; it reports RMS level and clipping. It does
not identify the radio from audio activity. Name, host API and channel are
saved; on capture the exact identity must uniquely match, even if numeric
indices changed. Missing or duplicate identities fail without fallback.
The guided saved cw_audio_identity takes precedence over legacy manual
cw_audio_device. Disconnecting a stream is handled as capture loss; no default
microphone is substituted. Device descriptions may be generic, so the operator
must identify the radio input. Main/Sub mapping remains hardware-dependent.
