import numpy as np
SR=16000
def _res(x, f, bw):
    from scipy.signal import lfilter
    r=np.exp(-np.pi*bw/SR); th=2*np.pi*f/SR
    return lfilter([1-r],[1,-2*r*np.cos(th),r*r],x)
def vowel(sec, f0=120, vib=0.0, amp=0.25, fade=0.4, seed=0):
    """Held 'ahhh': glottal pulse train through /a/ formants, steady, with exponential fade tail."""
    rng=np.random.default_rng(seed)
    n=int(SR*sec); t=np.arange(n)/SR
    ph=np.cumsum(2*np.pi*(f0*(1+vib*np.sin(2*np.pi*5*t)))/SR)
    src=np.sign(np.diff(np.floor(ph/(2*np.pi)),prepend=0))*1.0  # impulses
    src=src+0.02*rng.standard_normal(n)
    y=_res(_res(_res(src,800,90),1200,110),2500,170)
    y=y/np.max(np.abs(y))*amp
    env=np.ones(n); k=int(SR*fade); env[-k:]=np.exp(-np.linspace(0,6,k))
    return (y*env).astype(np.float32)
def word(sec, seed=1, amp=0.3):
    """Short 'word': vowel with syllable amplitude modulation (6 Hz)."""
    y=vowel(sec,f0=130,vib=0.03,amp=amp,fade=0.05,seed=seed)
    t=np.arange(len(y))/SR
    return (y*(0.55+0.45*np.sin(2*np.pi*3*t)**2)).astype(np.float32)
def room(sec, db=-58, seed=2):
    return (10**(db/20)*np.random.default_rng(seed).standard_normal(int(SR*sec))).astype(np.float32)
def build():
    parts=[]; marks={}
    def add(name,a): 
        s=sum(len(p) for p in parts); parts.append(a); marks[name]=(s/SR,(s+len(a))/SR)
    add('sil1',room(2.0,seed=3)); add('word1',word(0.7)+room(0.7,seed=4))
    add('sil2',room(1.5,seed=5)); add('ahhh',vowel(2.5,vib=0.01)+room(2.5,seed=6))
    add('sil3',room(2.0,seed=7)); add('word2',word(0.6,seed=9)+room(0.6,seed=8)); add('sil4',room(1.5,seed=10))
    return np.concatenate(parts).astype(np.float32), marks
