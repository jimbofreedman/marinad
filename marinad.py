#!/usr/bin/python3

import sys, socket, select, time
import soco
from datetime import datetime, timedelta
import forecastio
from contextlib import closing
from flask import Flask
import upnpclient

app = Flask(__name__)


def get_day_number():
    return (datetime.utcnow() - datetime(2018, 1, 1) - timedelta(hours=4)).days

my_bedroom_zone = soco.SoCo("172.16.0.222")
my_bathroom_zone = soco.SoCo("172.16.0.219")
my_tv_zone = soco.SoCo("172.16.0.196")
my_library = soco.music_library.MusicLibrary(my_bedroom_zone)


def set_daily_playlist():
    playlists = [3, 4, 6, 7, 8, 9, 10]
    index = get_day_number() % len(playlists)
    my_bedroom_zone.clear_queue()
    my_bedroom_zone.add_uri_to_queue("file:///jffs/settings/savedqueues.rsq#{}".format(str(playlists[index])))
    my_bedroom_zone.play_mode = 'SHUFFLE'  # this is actually SHUFFLE and REPEAT
    my_bedroom_zone.next()  # start with a random track


volumes = {
    "Living Room": 50,
    "Bathroom": 15,
    "Office": 10,
    "Bedroom": 10
}


@app.route("/reset_volumes")
def reset_volumes():
    for zone in soco.discover():
        zone.volume = volumes[zone.player_name]
        zone.mute = False
    return "Volumes reset"


@app.route("/regroup_speakers")
def regroup_speakers():
    my_bedroom_zone.unjoin()
    my_bedroom_zone.partymode()
    return "Speakers regrouped"


@app.route("/play_xbox_audio")
def play_xbox_audio():
    my_tv_zone.switch_to_line_in()
    my_bathroom_zone.join(my_tv_zone)
    return ("Playing Xbox audio")


@app.route("/stop_music")
def stop_music():
    my_bedroom_zone.stop()
    return("Stopped music")


@app.route("/play_music")
def play_music():
    # start a new track instead of resuming half-way through whatever was playing when we leave
    set_daily_playlist()
    my_bedroom_zone.play()
    my_bedroom_zone.next()
    return("Started music")


@app.route("/setup_music")
def setup_music():
    set_daily_playlist()
    return("Setup playlist")


dlna_server_uri = 'http://172.16.0.218:50002/v/NDLNA/'
yoga_videos = ['19909.mp4',
               '19915.mp4',
               '19917.mp4',
               '19916.mp4',
               '19927.mp4',
               '19928.mp4',
               '19929.mp4',
               '19930.mp4',
               '19931.mp4',
               '19932.mp4',
               '19933.mp4',
               '19934.mp4',
               '19935.mp4',
               '19914.mp4']


@app.route("/start_yoga_paused")
def start_yoga_paused():
    time.sleep(60)
    devices = upnpclient.discover()
    xbox = [d for d in devices if d.friendly_name == 'VANGUARD' and d.model_description == 'Digital Media Renderer'][0]
    service = [s for s in xbox.services if s.service_type == 'urn:schemas-upnp-org:service:AVTransport:1'][0]
    index = get_day_number() % len(yoga_videos)
    print(get_day_number(), index)
    uri = dlna_server_uri + yoga_videos[index]
    print(uri)
    service.SetAVTransportURI(InstanceID=0, CurrentURI=uri, CurrentURIMetaData="")
    time.sleep(5)
    service.Pause(InstanceID=0)
    return "Started yoga video"


# Create a client using the credentials and region defined in the adminuser
# section of the AWS credentials and configuration files
from boto3 import Session
import os
session = Session(profile_name="marina", region_name="eu-west-1")
polly = session.client("polly")

@app.route("/play_alarm")
def play_alarm():
    def say_time(time):
        return "<say-as interpret-as='time'>{}</say-as>".format(datetime.strftime(time, "%-I %p"))

    def emphasize(text):
        return "<emphasis>{}</emphasis>".format(text)

    def get_greeting():
        now = datetime.now()
        day_of_week = datetime.strftime(now, "%A")
        endings = [None, "st", "nd", "rd"]
        day = str(now.day) + ("th" if now.day > 3 else endings[now.day])
        month = datetime.strftime(now, "%B")
        return "<s>Good morning James.</s>\n<s>It's {} on {}, the {} of {}.</s>\n".format(say_time(now), day_of_week, day, month)

    def get_weather():
        def simplify_summary(summary):
            simplifications = {
                "Partly Cloudy": "clear",
                "Mostly Cloudy": "cloudy",
                "Overcast": "cloudy"
            }
            return simplifications[summary] if (summary in simplifications) else summary

        key = "b5170054ead98ceab7c9be7bb97c7dbc"
        forecast = forecastio.load_forecast(key, 51.509865, -0.118092)

        weather_now = forecast.currently()
        weather_start = simplify_summary(weather_now.summary)
        current_weather = "The weather is {} at {} degrees".format(emphasize(weather_start), emphasize(str(int(weather_now.temperature))))

        weather_today = forecast.hourly()
        day_forecast = ""
        max_temp = -50
        max_temp_hour = None
        for weather_hour in weather_today.data:

            if weather_hour.temperature > max_temp:
                max_temp = weather_hour.temperature
                max_temp_hour = weather_hour.time

            this_hour_summary = simplify_summary(weather_hour.summary)
            if (this_hour_summary != weather_start):
                day_forecast = day_forecast + "{} until {}, ".format(weather_start, say_time(weather_hour.time))
                weather_start = this_hour_summary

            if weather_hour.time.hour >= 23:
                break

        if (day_forecast == ""):
            day_forecast = "{} all day".format(emphasize(weather_start))

        max_temp = ", with a maximum of {} degrees at {}.".format(emphasize(str(int(max_temp))), say_time(max_temp_hour))

        return "<s>{}, and will be {} {}</s>".format(current_weather, day_forecast, max_temp)

    def get_incidents():
        return " There are no current incidents and you are not on call."

    def get_appointments():
        return " You have no appointments before standup."

    message = """
        <speak xmlns="http://www.w3.org/2001/10/synthesis" xmlns:dc="http://purl.org/dc/elements/1.1/" version="1.0">
            <p>
            {}
            {}
            {}
            {}
            </p>
        </speak>""".format(get_greeting(), get_incidents(), get_appointments(), get_weather())
    print(message)

    response = polly.synthesize_speech(Text=message,
                                       TextType='ssml',
                                       VoiceId="Emma",
                                       OutputFormat="mp3")

    def stream_data(stream, file):
        """Consumes a stream in chunks to produce the response's output'"""
        print("Streaming started...")

        if stream:
            with closing(stream) as managed_stream:
                while True:
                    data = managed_stream.read(1024)
                    file.write(b"%s" % (data))
                    if not data:
                        break
                file.flush()

            print("Streaming completed.")
        else:
            # The stream passed in is empty
            file.write(b"0\r\n\r\n")
            print("Nothing to stream.")

        print(response)

    with open("010voice.mp3", "wb") as file:
        stream_data(response.get("AudioStream"), file)

    os.system('ffmpeg -y -i /tmp/010voice.mp3 -filter:a "volume=2" /tmp/011loudvoice.mp3')
    os.system('ffmpeg -y -i concat:"000silence23.mp3|011loudvoice.mp3" -codec copy /tmp/012silencevoice.mp3')
    os.system('ffmpeg -y -i 001quietsong.mp3 -i /tmp/012silencevoice.mp3 -filter_complex "[0:0][1:0] amix=inputs=2:duration=longest" /Volumes/videos/alarm.wav')
    my_bedroom_zone.play_uri("x-file-cifs://volturnus/videos/alarm.wav")
    my_bedroom_zone.play_mode("NORMAL")
    return "Playing alarm"


if __name__ == "__main__":
    app.run()
