# About
**AutoPhone** is phone call automation tool which uses **Your Phone** Windows app for making calls.\
Windows 10 or later is only supported, but you can also run this on virtual machine with forwarded Bluetooth device.

### Requirements
- [Python 3](https://python.org)
- [Your Phone app](https://support.microsoft.com/phone-link)
- Bluetooth
- Audio routing software

# Setup
Create new folder, open PowerShell there and enter this command:
```
iwr -useb https://raw.githubusercontent.com/funcy2267/AutoPhone/main/setup.ps1 | iex
```
It will configure environment for you.\
Next, create 2 virtual audio line devices (output goes to input).\
Edit `settings.json` file for your case.\
To do this, use following scripts to get data:
- `audio_devices.py` - get information about connected audio devices
- `get_cursor.py` - get current position of mouse cursor

# Usage
Create Python file and program your phone calls like this:
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
