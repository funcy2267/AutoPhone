git clone https://github.com/funcy2267/AutoPhone.git
cp AutoPhone/config.yaml .

pip3 install -r AutoPhone/requirements.txt
pipwin install PyAudio

mkdir cache
mkdir ffmpeg

curl -UserAgent "Wget" "https://sourceforge.net/projects/capture2text/files/latest/download" -O "Capture2Text.zip"
curl "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -O "ffmpeg-release-essentials.zip"

tar -xvf "Capture2Text.zip"
tar -xvf "ffmpeg-release-essentials.zip" */bin/ffmpeg.exe
mv ffmpeg-*_build/bin/ffmpeg.exe ffmpeg/

rm *.zip
rm ffmpeg-*_build/ -Recurse
