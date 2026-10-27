"""Make the game sounds. Run this on your computer:  python make_sounds.py

Only the standard library is used, so this works anywhere. Every sound is a short
piece of 16 bit mono PCM written to sounds/<name>.wav. The pitch, length, loudness
and shape of each sound come from the "sound" section of data/game.json.
main.py only reads the finished files in sounds/.
"""

import array
import json
import math
import os
import wave

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(ROOT, "data", "game.json")
FULL_SCALE = 32767.0

# Samples of fade in and out, so a sound never starts or stops with a click.
EDGE = 60


def load_config():
    with open(DATA_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def glide(note, rate, volume, decay):
    """One sweeping note: the frequency walks from "from" to "to" while the
    loudness falls away."""
    total = max(1, int(round(note["seconds"] * rate)))
    peak = FULL_SCALE * volume
    frequency = note["from"]
    step = (note["to"] - note["from"]) / total
    phase = 0.0
    samples = []
    for index in range(total):
        time = index / rate
        edge = min(1.0, index / EDGE, (total - index) / EDGE)
        phase += math.tau * frequency / rate
        frequency += step
        value = math.sin(phase) * math.exp(-decay * time) * edge
        samples.append(int(round(value * peak)))
    return samples


def build():
    config = load_config()["sound"]
    rate = int(config["sample_rate"])
    folder = os.path.join(ROOT, config["folder"])
    os.makedirs(folder, exist_ok=True)

    made = []
    for name, spec in config["sounds"].items():
        samples = array.array("h")
        for note in spec["notes"]:
            samples.extend(glide(note, rate, spec["volume"], spec["decay"]))
        path = os.path.join(folder, f"{name}.wav")
        with wave.open(path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(samples.tobytes())
        made.append((f"{config['folder']}/{name}.wav", len(samples) / rate))

    for name, seconds in made:
        print(f"{name}  {seconds:.2f} s")
    print(f"{len(made)} sounds in {config['folder']}/, {rate} Hz mono")
    return made


if __name__ == "__main__":
    build()
