"""Debug the yt-dlp subprocess run from within Python."""
import glob
import hashlib
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

query = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"
cache_dir = "./playlist/cache"
key = hashlib.md5(query.encode()).hexdigest()
wav_path = os.path.join(cache_dir, f"{key}.wav")
raw_path = wav_path.replace(".wav", ".raw_download_%(id)s.%(ext)s")
print("raw_path:", raw_path)

ytdlp_base = [
    "yt-dlp",
    "--no-playlist",
    "--playlist-end", "1",
    "--max-filesize", "50m",
    "-f", "bestaudio/best",
    "-o", raw_path,
    "--quiet",
    "--no-warnings",
    query,
]

cmd = ytdlp_base[:]
cmd.insert(-2, "--match-filter")
cmd.insert(-2, "duration < 300")
print("cmd:", cmd)

result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=".")
print("rc:", result.returncode)
print("stdout:", result.stdout[:200])
print("stderr:", result.stderr[:300])

template_prefix = raw_path.split("%(")[0]
print("prefix:", template_prefix)
matches = glob.glob(f"{template_prefix}*")
print("glob matches:", matches)
