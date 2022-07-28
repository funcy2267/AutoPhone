import pyautogui as pag
from gtts import gTTS
from scipy.io.wavfile import write as wavfile_write
import speech_recognition as sr
import subprocess
import sounddevice as sd
import soundfile as sf
import numpy as np
import time
import json
import string

settings = json.load(open('settings.json', "r"))

audio_input = settings["audio"]["input"]
audio_output = settings["audio"]["output"]
screen_size = pag.size()

def call(number):
    pag.hotkey("win", str(settings["buttons"]["taskbar_app"]))
    time.sleep(0.5)
    pag.click(settings["buttons"]["view_calls"])
    time.sleep(0.5)
    pag.write(str(number), interval=0.1)
    pag.click(settings["buttons"]["call"])
    time.sleep(0.5)
    pag.hotkey("win", str(settings["buttons"]["taskbar_app"]))

def stt(timeout=3):
    mic = sr.Microphone(device_index=audio_input)
    with mic as source:
        print("Say something!")
        audio = sr.Recognizer().listen(source, phrase_time_limit=timeout)
    try:
        str = sr.Recognizer().recognize_google(audio, language=settings["languages"]["stt"]).lower()
        return(str)
    except sr.UnknownValueError:
        print("Google Speech Recognition could not understand audio")
    except sr.RequestError as e:
        print("Could not request results from Google Speech Recognition service; {0}".format(e))

def tts(text):
    try:
        tts = gTTS(text=text, lang=settings["languages"]["tts"])
        tts.save("cache/tts.mp3")
        subprocess.call(['ffmpeg/ffmpeg.exe', '-y', '-i', 'cache/tts.mp3', 'cache/tts.wav'])
        data, fs = sf.read("cache/tts.wav")
        sd.play(data, fs, device=(None, audio_output))
        sd.wait()
    except AssertionError:
        print("No text to speak")

def microphone_callback(indata, outdata, frames, time, status):
    global mic_volume
    mic_volume = int(np.linalg.norm(indata)*10)

def wait_for_call():
    global mic_volume
    mic_volume = 0
    while True:
        while mic_volume < 1:
            with sd.Stream(callback=microphone_callback, device=(audio_input, None)):
                sd.sleep(1000)
                print ("|" * mic_volume)
        number = get_caller_id()
        if number != '':
            break
    return(number)

def ocr_scan_area(area):
    output_file = 'cache/ocr.txt'
    subprocess.call(['Capture2Text/Capture2Text_CLI.exe', '--language', settings["languages"]["c2t"], '--whitelist', string.ascii_letters+string.digits+'+', '--output-file', output_file, '--screen-rect', " ".join(str(int(x)) for x in area)])
    f = open(output_file, "r")
    return(f.read().strip())

def get_caller_id():
    ocr_result = ocr_scan_area([screen_size[0]-(screen_size[0]/3), screen_size[1]/2, screen_size[0], screen_size[1]])
    print(ocr_result)
    number = ""
    for i in range(len(ocr_result)):
        character = ocr_result[i]
        if character == '+':
            while character in string.digits+'+ ':
                number += character
                i=i+1
                character = ocr_result[i]
            break
    return(number)

def answer_call():
    pag.click(settings["buttons"]["answer_call"])

def reject_call():
    pag.click(settings["buttons"]["reject_call"])

def end_call():
    pag.click(settings["buttons"]["end_call"])

def wait_for_answer():
    while True:
        ocr_result = ocr_scan_area([screen_size[0]-(screen_size[0]/3), 0, screen_size[0], screen_size[1]/3])
        print(ocr_result)
        if settings["wait_for_answer_word"] not in ocr_result.lower():
            break
        time.sleep(2)

def record(file, duration):
    fs = 44100
    recording = sd.rec(int(duration * fs), samplerate=fs, channels=2, device=(audio_input, None))
    sd.wait()
    wavfile_write(file, fs, recording)
