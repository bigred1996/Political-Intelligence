"""
Original soundtrack for the Nessus Intelligence teaser — FAST cut, v2.
Driving cinematic-electronic groove at 150 BPM (beat = 0.4s = exactly 12 frames
at 30fps) so the video can cut tightly on the beat. Fully synthesized with numpy
(no samples) => license-free.

  0.0-3.2s  intro build      atmos pad + riser -> DROP
  3.2-8s    stat slams       four-on-the-floor + bass + claps
  8-11.2s   sources unify    F
  11.2-15.2 entity merge     C
  15.2-19.2 connection web   G
  19.2-22   risk bars        Am
  22-25.6   proof flashes    F (busiest — sixteenth hats)
  25.6-27.6 ask nessus       C
  27.6-30   close            C major lift + final impact, fade

Output: public/music.wav (44.1kHz, 16-bit, stereo)
"""
import math, os, wave
import numpy as np

SR = 44100
DUR = 30.0
N = int(SR * DUR)
rng = np.random.default_rng(11)
BPM = 150.0
BEAT = 60.0 / BPM          # 0.4s
SIX = BEAT / 4.0           # sixteenth

def place(buf, sig, start_s, gain=1.0):
    s = int(start_s * SR)
    if s >= len(buf):
        return
    e = min(len(buf), s + len(sig))
    buf[s:e] += sig[: e - s] * gain

def expenv(n, k):
    return np.exp(-np.arange(n) / SR * k)

# ---- one-shot voices (synthesized once, then placed many times) ----
def make_kick():
    n = int(0.30 * SR); tt = np.arange(n) / SR
    f = 48 + (150 - 48) * np.exp(-tt * 42)
    phase = 2 * math.pi * np.cumsum(f) / SR
    body = np.sin(phase) * np.exp(-tt * 6.5)
    click = rng.standard_normal(n) * np.exp(-tt * 900) * 0.5
    return (body + click) * 0.95

def make_hat(closed=True):
    n = int((0.045 if closed else 0.16) * SR); tt = np.arange(n) / SR
    noise = rng.standard_normal(n)
    hp = noise - np.convolve(noise, np.ones(12) / 12, mode="same")  # crude high-pass
    return hp * np.exp(-tt * (75 if closed else 17)) * 0.4

def make_clap():
    n = int(0.22 * SR); tt = np.arange(n) / SR
    out = np.zeros(n)
    for off in (0.0, 0.009, 0.018):
        s = int(off * SR)
        seg = rng.standard_normal(n - s) * np.exp(-np.arange(n - s) / SR * 55)
        out[s:] += seg
    noise = rng.standard_normal(n)
    out = (out + 0.3 * noise * np.exp(-tt * 18))
    out -= np.convolve(out, np.ones(20) / 20, mode="same")  # brighten
    return out * 0.33

def stab(freqs, length=0.34):
    n = int(length * SR); tt = np.arange(n) / SR
    sig = np.zeros(n)
    for f in freqs:
        for h, a in ((1, 1.0), (2, 0.5), (3, 0.28), (4, 0.14)):
            sig += np.sin(2 * math.pi * f * h * tt) * a
    cut = np.exp(-tt * 7)                  # filter-ish decay via harmonic fade
    e = np.exp(-tt * 4.5)
    sig = sig * e * (0.4 + 0.6 * cut)
    sig /= (np.max(np.abs(sig)) + 1e-9)
    return sig * 0.16

def bass(freq, length):
    n = int(length * SR); tt = np.arange(n) / SR
    sig = np.sin(2 * math.pi * freq * tt) + 0.3 * np.sin(2 * math.pi * freq * 2 * tt)
    e = np.minimum(1.0, np.exp(-tt * 3.0) + 0.15)
    g = np.clip(1 - tt / length, 0, 1) ** 0.3
    return sig * e * g * 0.34

def pad(freqs, length, gain=0.16):
    n = int(length * SR); tt = np.arange(n) / SR
    sig = np.zeros(n)
    for f in freqs:
        for cents in (-0.005, 0.0, 0.005):
            sig += np.sin(2 * math.pi * f * (1 + cents) * tt + rng.uniform(0, 6.28))
    atk = int(min(0.5, length * 0.3) * SR); rel = int(min(0.8, length * 0.4) * SR)
    env = np.ones(n)
    env[:atk] = np.linspace(0, 1, atk)
    env[n - rel:] = np.linspace(1, 0, rel)
    lfo = 0.85 + 0.15 * np.sin(2 * math.pi * 0.5 * tt)
    sig = sig * env * lfo
    sig /= (np.max(np.abs(sig)) + 1e-9)
    return sig * gain

def riser(length):
    n = int(length * SR); tt = np.arange(n) / SR
    noise = rng.standard_normal(n)
    sm = np.convolve(noise, np.ones(40) / 40, mode="same")  # low-passed
    swell = sm * (tt / length) ** 2.0
    pitch = np.sin(2 * math.pi * (200 + 600 * (tt / length)) * tt) * (tt / length) ** 3 * 0.3
    return (swell * 0.5 + pitch) * 0.4

def impact(length=2.2):
    n = int(length * SR); tt = np.arange(n) / SR
    sig = np.sin(2 * math.pi * 55 * tt) + 0.5 * np.sin(2 * math.pi * 110 * tt)
    sig += rng.standard_normal(n) * np.exp(-tt * 30) * 0.4
    return sig * np.exp(-tt * 3.8) * 0.55

KICK, HATC, HATO, CLAP = make_kick(), make_hat(True), make_hat(False), make_clap()

# ---- chord map ----
A3, C4, E4, F3, A3b, C5, G3, B3, D4, G4, E3 = (220, 261.63, 329.63, 174.61, 220, 523.25, 196, 246.94, 293.66, 392, 164.81)
SECTIONS = [
    (0.0, 3.2, [A3, C4, E4], 55.0),
    (3.2, 8.0, [A3, C4, E4], 55.0),
    (8.0, 11.2, [F3, A3, C4], 87.31),
    (11.2, 15.2, [C4, E4, G4], 65.41),
    (15.2, 19.2, [G3, B3, D4], 49.0),
    (19.2, 22.0, [A3, C4, E4], 55.0),
    (22.0, 25.6, [F3, A3, C4], 87.31),
    (25.6, 27.6, [C4, E4, G4], 65.41),
    (27.6, 30.0, [C4, E4, G4, C5], 65.41),
]

dry = np.zeros(N)

# pads + bass + stabs per section
for (s, e, tones, b) in SECTIONS:
    place(dry, pad(tones, e - s, gain=0.14), s)
    place(dry, stab([t * 1 for t in tones], 0.5), s, gain=1.0)
    if s >= 3.2:  # gated bass on eighths
        bt = s
        while bt < e - 0.05:
            place(dry, bass(b, BEAT * 0.5), bt)
            bt += BEAT / 2

def chord_at(time_s):
    for (s, e, tones, b) in SECTIONS:
        if s <= time_s < e:
            return tones
    return SECTIONS[-1][2]

# drums from the drop (3.2s) to 28s
beat_t = 3.2
bi = 0
while beat_t < 28.0:
    place(dry, KICK, beat_t, gain=1.0)
    # claps on beats 2 & 4 from 7s
    if beat_t >= 7.0 and bi % 4 in (1, 3):
        place(dry, CLAP, beat_t, gain=0.9)
    beat_t += BEAT
    bi += 1

# hats — density grows; sixteenths in the busy "proof" section
hat_t = 3.2
hi = 0
while hat_t < 28.0:
    dense = 22.0 <= hat_t < 25.6
    step = SIX if dense else SIX * 2
    g = 1.0 if (hi % 2 == 1) else 0.5  # accent offbeats
    place(dry, HATC, hat_t, gain=g * (1.1 if dense else 0.85))
    if hi % 8 == 6:
        place(dry, HATO, hat_t, gain=0.7)
    hat_t += step
    hi += 1

# stabs/arps — sixteenth chord-tone plucks for energy in webs/proof
for (s, e) in [(11.2, 19.2), (22.0, 25.6)]:
    at = s; ai = 0
    while at < e:
        tones = chord_at(at)
        place(dry, stab([tones[ai % len(tones)] * 2], 0.18), at, gain=0.5)
        at += SIX * 2; ai += 1

# risers + impacts at section boundaries
for (s, e, tones, b) in SECTIONS[1:]:
    place(dry, riser(min(1.6, e - s)), max(0, s - 1.4))
    place(dry, impact(2.0), s, gain=0.8)
place(dry, riser(2.6), 0.4)  # intro build

# ---- stereo reverb + master ----
def reverb_ir(length, decay):
    n = int(length * SR); tt = np.arange(n) / SR
    ir = rng.standard_normal(n) * np.exp(-tt * decay)
    ir[: int(0.005 * SR)] = 0
    ir /= (np.sqrt(np.sum(ir ** 2)) + 1e-9)
    return ir

def conv(x, ir):
    L = len(x) + len(ir) - 1
    nf = 1 << (L - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, nf) * np.fft.rfft(ir, nf), nf)[: len(x)]

print("rendering reverb...")
wet_l = conv(dry, reverb_ir(1.7, 5.6))
wet_r = conv(dry, reverb_ir(1.7, 5.3))
WET = 0.22
left = np.tanh((dry + WET * wet_l) * 1.25)
right = np.tanh((dry + WET * wet_r) * 1.25)
peak = max(np.max(np.abs(left)), np.max(np.abs(right))) + 1e-9
left = left / peak * 0.94
right = right / peak * 0.94

# fades
fi = int(0.25 * SR); fo = int(28.6 * SR)
left[:fi] *= np.linspace(0, 1, fi); right[:fi] *= np.linspace(0, 1, fi)
left[fo:] *= np.linspace(1, 0, N - fo); right[fo:] *= np.linspace(1, 0, N - fo)

stereo = np.empty(N * 2)
stereo[0::2] = left; stereo[1::2] = right
pcm = np.int16(np.clip(stereo, -1, 1) * 32767)
out_path = os.path.join(os.path.dirname(__file__), "public", "music.wav")
with wave.open(out_path, "w") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print("wrote", out_path, "| dur", round(N / SR, 2), "s | peak", round(float(peak), 3))
