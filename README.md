# About
**AutoPhone** is phone call automation tool which uses **Your Phone** Windows app for making calls.\
Windows 10 or later is only supported, but you can also run this on virtual machine with forwarded Bluetooth device.

### Requirements
- [Python 3](https://python.org)
- [Git](https://gitforwindows.org)
- [Your Phone app](https://support.microsoft.com/phone-link)
- Android device
- Bluetooth
- Audio routing software

# Setup

### Your Phone
Connect your Android device with **Your Phone** app.

### Environment
Create new folder, open PowerShell there and enter this command:
```
iwr -useb https://raw.githubusercontent.com/funcy2267/AutoPhone/main/setup.ps1 | iex
```
You may need to [install your language](http://capture2text.sourceforge.net/#install_additional_languages) for **Capture2Text**.

### Audio routing
Use 2 virtual audio line devices (output goes to input).\
Set system default output to `Line 1` and input to `Line 2`.

### Config
Edit `config.yaml` file for your case.\
To do this, use following scripts to get data:
- `audio_devices.py` - get information about audio devices
- `get_cursor.py` - get current position of mouse cursor

# Usage
Create new Python file and program your phone calls like this:
```
from AutoPhone import your_phone

# your_phone.call(number) - call number
# your_phone.stt(timeout) - recognize speech and return result (timeout is optional)
# your_phone.tts(text) - say with text to speech
# your_phone.wait_for_call() - wait for incoming calls and return caller's phone number
# your_phone.answer_call() - answer call
# your_phone.reject_call() - reject call
# your_phone.end_call() - end call
# your_phone.wait_for_answer() - wait for call answer
# your_phone.record(file, duration) - record audio to .wav file with duration
```
