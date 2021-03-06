"""
This class implement the clustering of triggers found by wdf pipeline
  .. function:: Cluster(triggers,deltaT,deltaSNR)

   :module: wdml.observers.clustering
"""

import logging
from collections import defaultdict
from heapq import nlargest

from numpy.fft import fft
from pytsa.tsa import *
from scipy import signal, integrate

from wdfml.observers.observable import Observable
from wdfml.observers.observer import Observer
from wdfml.structures.array2SeqView import *
from wdfml.structures.eventPE import *

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def estimate_freq_mean ( sig, fs ):
    freq, psd = signal.welch(sig, fs, window='hanning', nperseg=len(sig), noverlap=None, nfft=None, detrend=False,
                             return_onesided=True, scaling='density', axis=-1)

    threshold = np.mean(psd)
    mask = np.abs(psd) >= threshold
    peaks = freq[mask]
    freq_mean = peaks.mean()
    return freq_mean


def wave_freq ( sig, fs ):
    domain = float(len(sig))
    assert domain > 0
    index = np.argmax(abs(fft(sig)[1:])) + 2
    if index > len(sig) / 2:
        index = len(sig) - index + 2
    freq = (fs / domain) * (index - 1)
    return freq


def estimate_freq_mean_max ( sig, fs ):
    nperseg = np.ceil(len(sig))
    f, P = signal.welch(sig, fs, window='hanning', nperseg=nperseg, noverlap=None, nfft=len(sig), detrend=False, \
                        return_onesided=True, scaling='spectrum', axis=-1)
    Area = integrate.cumtrapz(P, f, initial=0)
    Ptotal = Area[-1]
    mpf = integrate.trapz(f * P, f) / Ptotal  # mean power frequency
    fmax = f[np.argmax(P)]
    return mpf, fmax


class ParameterEstimation(Observer, Observable):
    def __init__ ( self, parameters ):
        """
        :type parameters: class Parameters object
        """
        Observable.__init__(self)
        Observer.__init__(self)
        self.sampling = parameters.resampling
        self.Ncoeff = parameters.Ncoeff
        self.scale = int(np.log2(parameters.Ncoeff))
        self.snr = parameters.threshold
        self.ARsigma = parameters.sigma
        self.df = (self.sampling / self.Ncoeff)  # *np.sqrt(2)

    def update ( self, event ):
        wave = event.mWave
        t0 = event.mTime
        logging.info(str(t0))
        coeff = np.zeros(self.Ncoeff)
        Icoeff = np.zeros(self.Ncoeff)
        for i in range(self.Ncoeff):
            coeff[i] = event.GetCoeff(i)
        sigma = 1.0 / (event.mSNR / np.sqrt(np.sum([x * x for x in coeff])))
        #### here we reconstruct really the event in the wavelet plane

        new = np.zeros((int(self.scale), int(2 ** ((self.scale) - 1))))
        dnew = defaultdict(list)

        for j in range(int(self.scale)):
            for k in range(int(2 ** (j - 1))):
                new[j, k] = coeff[j + k]
                dnew[new[j, k]].append((j, k))

        for value, positions in nlargest(1, dnew.items(), key=lambda item: item[0]):
            index0 = positions[0][0] + positions[0][1]
            scale0 = positions[0][0]
            value0 = value
            maxvalue = (scale0, index0, value0)

        indicesnew = []
        valuesnew = []
        for value, positions in nlargest(self.Ncoeff, dnew.items(), key=lambda item: item[0]):
            index = positions[0][0] + positions[0][1]
            if np.abs(index - index0) / index0 < 0.1:
                indicesnew.append(index)
                valuesnew.append(value)
                index0 = index

        for i in range(self.Ncoeff):
            if i not in indicesnew:
                coeff[i] = 0.0

        data = array2SeqView(t0, self.sampling, self.Ncoeff)
        data = data.Fill(t0, coeff)
        dataIdct = array2SeqView(t0, self.sampling, self.Ncoeff)
        dataIdct = dataIdct.Fill(t0, coeff)
        if event.mWave != 'DCT':
            wt = getattr(WaveletTransform, wave)
            WT = WaveletTransform(self.Ncoeff, wt)
            WT.Inverse(data)
            for i in range(self.Ncoeff):
                Icoeff[i] = data.GetY(0, i)
        else:
            idct = IDCT(self.Ncoeff)
            idct(data, dataIdct)
            for i in range(self.Ncoeff):
                Icoeff[i] = dataIdct.GetY(0, i)

        timeDuration = np.abs(np.max(indicesnew) - np.min(indicesnew)) / self.sampling
        timeDetailnew = np.float(maxvalue[1]) / self.sampling
        #timeDetailnew = np.median(indicesnew)/ self.sampling
        snrDetailnew = np.sqrt(np.sum([x * x for x in valuesnew]))
        tnew = t0 + timeDetailnew

        snrMax = snrDetailnew / (sigma)  # *self.df)
        snr = event.mSNR  # /self.df
        freqatpeak = wave_freq(Icoeff, self.sampling)
        freq = estimate_freq_mean(Icoeff, self.sampling)
        eventParameters = eventPE(tnew, snr, snrMax, freq, freqatpeak, timeDuration, wave, coeff, Icoeff)
        self.update_observers(eventParameters)
