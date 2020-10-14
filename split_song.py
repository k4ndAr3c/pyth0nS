#!/usr/bin/env python3
import pydub, sys, requests
import re, json, os
from argparse import ArgumentParser
from pydub.silence import split_on_silence
import musicbrainzngs as mb
#from getpass import getpass

WARNING = '\033[93m'
ENDC = '\033[0m'
OKBLUE = '\033[94m'
BOLD = '\033[1m'

parser = ArgumentParser(prog=sys.argv[0])
parser.add_argument('-g', "--group", type=str, help='Group')
parser.add_argument('-a', "--album", type=str, help='Album')
parser.add_argument('-f', "--file", type=str, help='File')
parser.add_argument('-s', "--silence", type=int, help='Silence time duration', default=1000)
parser.add_argument('-n', "--number", type=int, help='Number of songs')
args = parser.parse_args()

if args.number is None: exit('How many songs must we have ?')

def searchTitles():
    titles_dic = {}
    mb.set_useragent("Example music app", "0.1", "http://example.com/music")
    r = mb.search_recordings(args.album)
    #r = mb.search_releases(args.album)
    #print(dir(mb))
    print()
    for _r in range(len(r["recording-list"])):
        try:
            tmp = r["recording-list"][_r]["release-list"][0]["title"]
            tmp2 = r["recording-list"][_r]["release-list"][0]["artist-credit"][0]["name"]
            #print(tmp2)
            if (tmp.lower().strip() in args.album.lower() and args.group.lower() == tmp2.lower().strip()) or (args.album.lower() in tmp.lower().strip() and args.group.lower() == tmp2.lower().strip()):
                tmp_id = r["recording-list"][_r]['id']
                print(tmp_id)
                print(tmp, ":", tmp2)
                for _m in r["recording-list"][_r]["release-list"][0]["medium-list"]:
                    _m = _m["track-list"][0]
                    titles_dic[_m["number"]] = _m["title"]
                    print(_m["number"], ":", _m["title"])
                    print("-"*42)

        except Exception as ex:
            print(ex, ":", tmp)

    return titles_dic

        #result = mb.get_releases_by_discid(tmp_id, includes=['artists', 'recordings'])
        ##result = mb.get_release_by_cdtext(performer=args.group, title=args.album, num_tracks=args.number)
        #print(result)

        ##if release.get('disc'):
        ##    this_release=release['disc']['release-list'][0]
        ##    title = this_release['title']
        ##    artist = this_release['artist-credit'][0]['artist']['name']
        #if result.get("disc"):
        #    print("artist:\t%s" % result["disc"]["release-list"][0]["artist-credit-phrase"])
        #    print("title:\t%s" % result["disc"]["release-list"][0]["title"])
        #elif result.get("cdstub"):
        #    print("artist:\t" % result["cdstub"]["artist"])
        #    print("title:\t" % result["cdstub"]["title"])

        #    if this_release['cover-art-archive']['artwork'] == 'true':
        #       url = 'http://coverartarchive.org/release/' + this_release['id']
        #       art = json.loads(requests.get(url, allow_redirects=True).content)
        #       for image in art['images']:
        #          if image['front'] == True:
        #             cover = requests.get(image['image'],
        #                                  allow_redirects=True)
        #             fname = '{0} - {1}.jpg'.format(artist, title)
        #             print('COVER="{}"'.format(fname))
        #             f = open(fname, 'wb')
        #             f.write(cover.content)
        #             f.close()
        #             break
        #
        #    print('TITLE="{}"'.format(title))
        #    print('ARTIST="{}"'.format(artist))
        #    print('YEAR="{}"'.format(this_release['date'].split('-')[0]))
        #    for medium in this_release['medium-list']:
        #       for disc in medium['disc-list']:
        #          if disc['id'] == this_disc.id:

def find_silence_length(f):
    blanks = [0]
    _l = 1700
    while len(blanks) != args.number:
        sys.stdout.write("{}.".format(_l))
        sys.stdout.flush()
        s = pydub.AudioSegment.silent(duration=_l)
        for i in range(0, len(f.raw_data), len(s.raw_data)):
            if f.raw_data[i:i+len(s.raw_data)] == s.raw_data:
                blanks.append(i)
        if len(blanks) == args.number:
            break
        else:
            blanks = [0]
            _l += 100

    blanks.append(len(f.raw_data))
    return blanks

def getFiles(params):
      inputlist = os.listdir(params)
      outputlist = []
      for data in inputlist:
            outputlist.append(params+data)
      return outputlist

def getAlbumArt(function, artist, name):
      try:
            url = "http://ws.audioscrobbler.com/2.0/?method=track.getInfo&api_key=348b4a08fda8a9b3c5a1ab7b2937f071&artist={0}&track={1}&format=json".format(artist.lower(),name.lower())
            url = url.replace(' ','%20')
            urldata = urllib.urlopen(url)
            data = urldata.read()
            js = json.loads(data)
            imagelink = js['track']['album']['image'][2]['#text']
            return imagelink
      except:
            return False

def loadfile(location):
    import eyed3
    audiofile = eyed3.load(location)
    print("Opened {0} in EyeD3".format(location))
    return audiofile

def getData(name):
      url = 'http://tinysong.com/b/{0}?format=json&key=ac948d3bb6b0c253274f5e4d52bf9543'.format(name) #You can use your own API key as well
      data = requests.get(url).text
      print(data)
      if len(data)<10:
            print("No JSON data available for {0}. Skipping it.\n".format(name))
            return False
      else:
            jsondata=json.loads(data)
            return jsondata

def modify(function, artist, album, title):
      function.tag.artist = artist
      function.tag.title = title
      function.tag.album = album
      function.tag.save()
      return True

def main():
    ts = searchTitles()
    print(ts)
    f = pydub.AudioSegment.from_file(args.file)
    print("len:", len(f)/1000/60, "min")
    songs = split_on_silence(f, min_silence_len=args.silence, silence_thresh=-40, keep_silence=100)
    if len(songs) != args.number:
        print('Bad split, wrong number of songs. (opt){} != {}'.format(args.number, len(songs)))
        resp = input("Continue ? ")
        if resp.lower() != "y":
            exit("Canceled.")
    for _s in range(len(songs)):
        song = songs[_s]
        try:
            title = ts[str(_s+1)]
            sub_title = "{}-{}".format(_s+1, title.replace(" ", "_"))
        except Exception as ex:
            print(ex)
            sub_title = "{}-{}".format(_s+1, args.album.replace(" ", "_"))

        try:
            filename = "/tmp/{}-{}.mp3".format(sub_title, args.group.replace(" ", "_"))
            file_handle = song.export(filename,
                                   format="mp3",
                                   #bitrate="192k",
                                   tags={"album": args.album, "artist": args.group, "title": sub_title},
                                   #cover="/path/to/albumcovers/radioheadthebends.jpg"
                                )
            print("[+] file {} saved :)".format(filename))
            #function = loadfile(filename)
            #status = modify(function, args.group, args.album, sub_title)
            #if not status:
            #    print("Error")
        except Exception as ex:
            print(ex)

if __name__=='__main__':
      main()
