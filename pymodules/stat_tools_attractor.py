#!/usr/bin/env python
'''
Module to perform various statistics on the data
(anisotropy estimation, spectral slope computation, WAR statistics, etc).

Documentation convention from https://github.com/numpy/numpy/blob/master/doc/HOWTO_DOCUMENT.rst.txt

26.09.2016
Loris Foresti
'''
from __future__ import division
from __future__ import print_function

import sys
import time
import numpy as np
import math
import pywt

import matplotlib.pyplot as plt

from scipy import stats, fftpack
import scipy.signal as ss
import scipy.ndimage as ndimage
from skimage import measure
import radialprofile

import pandas as pd
import statsmodels.formula.api as sm
from statsmodels.nonparametric.api import KernelReg

import scipy as sp
import scipy.spatial.distance as dist

fmt2 = "%.2f"

def compute_war(rainfield, rainThreshold, noData):
    idxRain = rainfield >= rainThreshold
    idxRadarDomain = rainfield > noData + 1
    
    if (len(idxRain) >= 0) and (len(idxRain) < sys.maxsize) and \
    (len(idxRadarDomain) >= 0) and (len(idxRadarDomain) < sys.maxsize) \
    and (np.sum(idxRain) <= np.sum(idxRadarDomain)) and (np.sum(idxRadarDomain) > 0):
        war = 100.0*np.sum(idxRain)/np.sum(idxRadarDomain)
    else:
        print("Problem in the computation of WAR. idxRain = ", idxRain, " and idxRadarDomain = ", idxRadarDomain, " are not valid values.")
        print("WAR set to -1")
        war = -1
    return war

def compute_war_array(rainfieldArray, rainThreshold, noData):
    warArray = []
    for i in range(0,len(rainfieldArray)):
        war = compute_war(rainfieldArray[i], rainThreshold, noData)
        warArray.append(war)
    warArray = np.array(warArray)
    return(warArray)
    
def compute_beta(logScale, logPower):
    beta, intercept, r_beta, p_value, std_err = stats.linregress(logScale, logPower)
    return(beta, intercept, r_beta)
    
def compute_beta_weighted(logScale, logPower, weights):
        # normalize sum of weights to 1
        weights = weights/float(np.sum(weights))
          
        degree = 1
        coefficients = np.polynomial.polynomial.polyfit(logScale, logPower, degree, w=weights)
        intercept = coefficients[0]
        beta = coefficients[1]
        
        # Get coefficient of correlation (it should also be adapted to weight more the sparser sets of points...)
        yhat = coefficients[0] + coefficients[1]*logScale   # Prediction model
        #ybar = np.sum(logPower)/len(logPower)          # Unweighted average of the predictand
        ybar = np.sum(weights*logPower)/np.sum(weights) # Weighted average of the predictand
        ssreg = np.sum(weights*(yhat-ybar)**2)           # Regression sum of squares
        sstot = np.sum(weights*(logPower - ybar)**2)      # Total sum of squares
        r_betaSq = ssreg/sstot
        
        if beta >= 0:
            r_beta = np.sqrt(r_betaSq)
        else:
            r_beta = -np.sqrt(r_betaSq)
            
        return(beta, intercept, r_beta)

def compute_beta_sm(logScale, logPower, weights = None):
    x_list = logScale.tolist()
    y_list = logPower.tolist()
    
    ws = pd.DataFrame({
    'x': x_list,
    'y': y_list
    })

    # Compute weighted or unweighted OLS
    if weights is not None:
        weightsPD = pd.Series(weights)
        results = sm.wls('y ~ x', data=ws, weights=weightsPD).fit()
    else:
        results = sm.ols('y ~ x', data=ws).fit()
    
    # Get results
    r_betaSq = results.rsquared
    beta = results.params.x
    intercept = results.params.Intercept

    if beta >= 0:
        r_beta = np.sqrt(r_betaSq)
    else:
        r_beta = -np.sqrt(r_betaSq)
    return(beta, intercept, r_beta)
    
def GaussianKernel(v1, v2, sigma):
    return exp(-norm(v1-v2, 2)**2/(2.*sigma**2))

def compute_2d_spectrum(rainfallImage, resolution=1, window=None, FFTmod='NUMPY'):
    '''
    Function to compute the 2D FFT power spectrum.
    
    Parameters
    ----------
    rainfallImage : numpyarray(float)
        Input 2d array with the rainfall field (or any kind of image)
    resolution : float
        Resolution of the image grid (e.g. in km) to compute the Fourier frequencies
    '''
    
    fieldSize = rainfallImage.shape
    minFieldSize = np.min(fieldSize)
    
    # Generate a window function
    if window == 'blackman':
        w1d = ss.blackman(minFieldSize)
        w = np.outer(w1d,w1d)
    elif window == 'hanning':
        w1d = np.hanning(minFieldSize)
        w = np.outer(w1d,w1d)
    else:
        w = np.ones((fieldSize[0],fieldSize[1]))    
    
    # Compute FFT
    if FFTmod == 'NUMPY':
        fprecipNoShift = np.fft.fft2(rainfallImage*w) # Numpy implementation
    if FFTmod == 'FFTW':
        fprecipNoShift = pyfftw.interfaces.numpy_fft.fft2(rainfallImage*window) # FFTW implementation
        # Turn on the cache for optimum performance
        pyfftw.interfaces.cache.enable()
    
    # Shift 2D spectrum
    fprecip = np.fft.fftshift(fprecipNoShift)
    
    # Compute 2D power spectrum
    psd2d = np.abs(fprecip)**2/(fieldSize[0]*fieldSize[1])    
    
    # Compute frequencies
    freqNoShift = fftpack.fftfreq(minFieldSize, d=float(resolution))
    freq = np.fft.fftshift(freqNoShift)
    
    return(psd2d, freq)

def compute_radialAverage_spectrum(psd2d, resolution=1):
    '''
    Function to compute the 1D radially averaged spectrum from the 2D spectrum.
    
    Parameters
    ----------
    psd2d : numpyarray(float)
        Input 2d array with the power spectrum.
    resolution : float
        Resolution of the image grid (e.g. in km) to compute the Fourier frequencies
    '''
    
    fieldSize = psd2d.shape
    minFieldSize = np.min(fieldSize)
    
    bin_size = 1
    nr_pixels, bin_centers, psd1d = radialprofile.azimuthalAverage(psd2d, binsize=bin_size, return_nr=True)
    
    # Extract subset of spectrum
    validBins = (bin_centers < minFieldSize/2) # takes the minimum dimension of the image and divide it by two
    psd1d = psd1d[validBins]
    
    # Compute frequencies
    freqNoShift = fftpack.fftfreq(minFieldSize, d=float(resolution))
    freqAll = np.fft.fftshift(freqNoShift)
    
    # Select only positive frequencies
    freq = freqAll[len(psd1d):]
    
    # Compute wavelength [km]
    with np.errstate(divide='ignore'):
        wavelength = resolution*(1.0/freq)
    # Replace 0 frequency with NaN
    freq[freq==0] = np.nan
    
    return(psd1d, freq, wavelength)
    
def compute_fft_anisotropy(psd2d, fftSizeSub = -1, percentileZero = -1, rotation = True, radius = -1, sigma = -1, verbose = 0):
    ''' 
    Function to compute the anisotropy from a 2d power spectrum or autocorrelation function.
    
    Parameters
    ----------
    psd2d : numpyarray(float)
        Input 2d array with the autocorrelation function or the power spectrum
    fftSizeSub : int
        Half-size of the sub-domain to extract to zoom in (maximum = psd2d.size[0]/2)
    percentileZero : int
        Percentile to use to shift the autocorrelation/spectrum to 0. Values below the percentile will be set to 0.
    rotation : bool
        Whether to rotate the spectrum (Fourier spectrum needs a 90 degrees rotation w.r.t autocorrelation)
    radius : int
        Radius in pixels from the center to mask the data (not needed if using the percentile criterion)
    sigma : float
        Bandwidth of the Gaussian kernel used to smooth the 2d spectrum (not needed for the autocorrelation function, already smooth)
    verbose: int
        Verbosity level to use (0: nothing is printed)
    
    Returns
    -------
    psd2dsub : numpyarray(float)
        Output 2d array with the autocorrelation/spectrum selected on the subdomain (and rotated if asked)
    eccentricity : float
        Eccentricity of the anisotropy (sqrt(1-eigval_max/eigval_min)) in range 0-1
    orientation : float
        Orientation of the anisotropy (degrees using trigonometrical convention, -90 degrees -> South, 90 degrees -> North, 0 degrees -> East)
    xbar : float
        X-coordinate of the center of the intertial axis of anisotropy (pixels)
    ybar : float
        Y-coordinate of the center of the intertial axis of anisotropy (pixels)
    eigvals : numpyarray(float)
        Eigenvalues obtained after decomposition of covariance matrix using selected values of spectrum/autocorrelation
    eigvecs : numpyarray(float)
        Eigenvectors obtained after decomposition of covariance matrix using selected values of spectrum/autocorrelation
    percZero : float
        Value of the autocorrelation/spectrum corresponding to the asked percentile (percentileZero)
    psd2dsubSmooth: numpyarray(float)
        Output 2d array with the smoothed autocorrelation/spectrum selected on the subdomain (and rotated if asked)
    '''
    
    # Get dimensions of the large and subdomain
    if fftSizeSub == -1:
        fftSizeSub = psd2d.shape[0]/2
    
    fftSize = psd2d.shape
    
    if ((fftSize[0] % 2) != 0) or ((fftSize[1] % 2) != 0):
        print("Error in compute_fft_anisotropy: please provide an even sized 2d FFT spectrum.")
        sys.exit(1)
    fftMiddleX = fftSize[1]/2
    fftMiddleY = fftSize[0]/2
    
    # Select subset of autocorrelation/spectrum
    psd2dsub = psd2d[fftMiddleY-fftSizeSub:fftMiddleY+fftSizeSub,fftMiddleX-fftSizeSub:fftMiddleX+fftSizeSub]

    ############### CIRCULAR MASK
    # Apply circular mask from the center as mask (not advised as it will often yield a circular anisotropy, in particular if the radisu is small)
    if radius != -1:
        # Create circular mask
        y,x = np.ogrid[-fftSizeSub:fftSizeSub, -fftSizeSub:fftSizeSub]
        mask = x**2+y**2 <= radius**2
        
        # Apply mask to 2d spectrum
        psd2dsub[~mask] = 0.0
    
    ############### ROTATION
    # Rotate FFT spectrum by 90 degrees
    if rotation:
        psd2dsub = np.rot90(psd2dsub)

    ############### SMOOTHING
    # Smooth spectrum field if too noisy (to help the anisotropy estimation)
    if sigma > 0:
        psd2dsubSmooth = ndimage.gaussian_filter(psd2dsub, sigma=sigma)
    else:
        psd2dsubSmooth = psd2dsub.copy() # just to give a return value...
    
    ############### SHIFT ACCORDING TO PERCENTILE
    # Compute conditional percentile on smoothed spectrum/autocorrelation
    minThresholdCondition = 0.01 # Threshold to compute to conditional percentile (only values greater than this)
    if percentileZero > 0:
        percZero = np.nanpercentile(psd2dsubSmooth[psd2dsubSmooth > minThresholdCondition], percentileZero)
    else:
        percZero = np.min(psd2dsubSmooth)
    
    if percZero == np.nan:
        percZero = 0.0
    
    # Treat cases where percentile is not a good choice and take a minimum correlation value (does not work with 2d spectrum)
    autocorrThreshold = 0.2
    if (percZero > 0) and (percZero < autocorrThreshold):
        percZero = autocorrThreshold
    
    # Shift spectrum/autocorrelation to start from 0 (zeros will be automatically neglected in the computation of covariance)
    psd2dsubSmoothShifted = psd2dsubSmooth - percZero
    psd2dsubSmoothShifted[psd2dsubSmoothShifted < 0] = 0.0
    
    ############### IMAGE SEGMENTATION
    # Image segmentation to remove high autocorrelations/spectrum values at far ranges/high frequencies
    psd2dsubSmoothShifted_bin = np.uint8(psd2dsubSmoothShifted > minThresholdCondition)
    
    # Compute image segmentation
    labelsImage = measure.label(psd2dsubSmoothShifted_bin, background = 0)
    
    # Get label of center of autocorrelation function (corr = 1.0)
    labelCenter = labelsImage[labelsImage.shape[0]/2,labelsImage.shape[1]/2]
    
    # Compute mask to keep only central polygon
    mask = (labelsImage == labelCenter).astype(int)
    
    nrNonZeroPixels = np.sum(mask)
    if verbose == 1:
        print("Nr. central pixels used for anisotropy estimation: ", nrNonZeroPixels)
    
    ############### COVARIANCE DECOMPOSITION
    # Find inertial axis and covariance matrix
    xbar, ybar, cov = _intertial_axis(psd2dsubSmoothShifted*mask)
    
    # Decompose covariance matrix
    eigvals, eigvecs = np.linalg.eigh(cov)
    
    ############### ECCENTRICITY/ORIENTATION
    # Compute eccentricity and orientation of anisotropy
    idxMax = np.argmin(eigvals)
    #eccentricity = np.max(np.sqrt(eigvals))/np.min(np.sqrt(eigvals))
    eccentricity = math.sqrt(1-np.min(eigvals)/np.max(eigvals))
    orientation = np.degrees(math.atan(eigvecs[0,idxMax]/eigvecs[1,idxMax]))
        
    return psd2dsub, eccentricity, orientation, xbar, ybar, eigvals, eigvecs, percZero, psd2dsubSmooth

def compute_autocorrelation_fft2(imageArray, FFTmod = 'NUMPY'):
    '''
    This function computes the autocorrelation of an image using the FFT.
    It exploits the Wiener-Khinchin theorem, which states that the Fourier transform of the auto-correlation function   
    is equal to the Fourier transform of the signal. Thus, the autocorrelation function can be obtained as the inverse transform of
    the power spectrum.
    It is very important to know that the auto-correlation function, as it is referred to as in the literature, is in fact the noncentred
    autocovariance. In order to obtain values of correlation between -1 and 1, one must center the signal by removing the mean before
    computing the FFT and then divide the obtained auto-correlation (after inverse transform) by the variance of the signal.
    '''
    
    tic = time.clock()
    
    # Compute field mean and variance
    field_mean = np.mean(imageArray)
    field_var = np.var(imageArray)
    field_dim = imageArray.shape
    
    # Compute FFT
    if FFTmod == 'NUMPY':
        fourier = np.fft.fft2(imageArray - field_mean) # Numpy implementation
    if FFTmod == 'FFTW':
        fourier = pyfftw.interfaces.numpy_fft.fft2(imageArray - field_mean) # FFTW implementation
        # Turn on the cache for optimum performance
        pyfftw.interfaces.cache.enable()
    
    # Compute power spectrum
    powerSpectrum = np.abs(fourier)**2/(field_dim[0]*field_dim[1])
    
    # Compute inverse FFT of spectrum
    if FFTmod == 'NUMPY':
        autocovariance = np.fft.ifft2(powerSpectrum) # Numpy implementation
    if FFTmod == 'FFTW':
        autocovariance = pyfftw.interfaces.numpy_fft.ifft2(powerSpectrum) # FFTW implementation
        # Turn on the cache for optimum performance
        pyfftw.interfaces.cache.enable()
    
    # Compute auto-correlation from auto-covariance
    autocorrelation = autocovariance.real/field_var
    
    # Shift autocorrelation function and spectrum to have 0 lag/frequency in the center
    autocorrelation_shifted = np.fft.fftshift(autocorrelation)
    powerSpectrum_shifted = np.fft.fftshift(powerSpectrum) # Add back mean to spectrum??
    
    toc = time.clock()
    #print("Elapsed time for ACF using FFT: ", toc-tic, " seconds.")
    return(autocorrelation_shifted, powerSpectrum_shifted)

def compute_autocorrelation_fft(timeSeries, FFTmod = 'NUMPY'):
    '''
    This function computes the autocorrelation of a time series using the FFT.
    It exploits the Wiener-Khinchin theorem, which states that the Fourier transform of the auto-correlation function   
    is equal to the Fourier transform of the signal. Thus, the autocorrelation function can be obtained as the inverse transform of
    the power spectrum.
    It is very important to know that the auto-correlation function, as it is referred to as in the literature, is in fact the noncentred
    autocovariance. In order to obtain values of correlation between -1 and 1, one must center the signal by removing the mean before
    computing the FFT and then divide the obtained auto-correlation (after inverse transform) by the variance of the signal.
    '''
    
    tic = time.clock()
    
    # Compute field mean and variance
    field_mean = np.mean(timeSeries)
    field_var = np.var(timeSeries)
    nr_samples = len(timeSeries)
    
    # Compute FFT
    if FFTmod == 'NUMPY':
        fourier = np.fft.fft(timeSeries - field_mean) # Numpy implementation
    if FFTmod == 'FFTW':
        fourier = pyfftw.interfaces.numpy_fft.fft(timeSeries - field_mean) # FFTW implementation
        # Turn on the cache for optimum performance
        pyfftw.interfaces.cache.enable()
    
    # Compute power spectrum
    powerSpectrum = np.abs(fourier)**2/nr_samples
    
    # Compute inverse FFT of spectrum
    if FFTmod == 'NUMPY':
        autocovariance = np.fft.ifft(powerSpectrum) # Numpy implementation
    if FFTmod == 'FFTW':
        autocovariance = pyfftw.interfaces.numpy_fft.ifft(powerSpectrum) # FFTW implementation
        # Turn on the cache for optimum performance
        pyfftw.interfaces.cache.enable()
    
    # Compute auto-correlation from auto-covariance
    autocorrelation = autocovariance.real/field_var
    
    # Take only first half (the autocorrelation and spectrum are symmetric)
    autocorrelation = autocorrelation[0:nr_samples/2]
    powerSpectrum = powerSpectrum[0:nr_samples/2]
    
    toc = time.clock()
    #print("Elapsed time for ACF using FFT: ", toc-tic, " seconds.")
    return(autocorrelation, powerSpectrum)

def time_delay_embedding(timeSeries, nrSteps=1, stepSize=1, noData=np.nan):
    timeSeries = np.array(timeSeries)
    
    nrSamples = len(timeSeries)
    delayedArray = np.ones((nrSamples,nrSteps+1))*noData
    delayedArray[:,0] = timeSeries
    
    for i in range(1,nrSteps+1):
        # Generate nodata to append to the delayed time series
        if i*stepSize <= nrSamples:
            timeSeriesNoData = noData*np.ones(i*stepSize)
        else:
            timeSeriesNoData = noData*np.ones(nrSamples)
        
        # Get the delayed time series segment
        timeSeriesSegment = timeSeries[i*stepSize:]
        timeSeriesSegment = np.hstack((timeSeriesSegment, timeSeriesNoData)).tolist()
        
        delayedArray[:,i] = timeSeriesSegment
    
    return(delayedArray)
        
def correlation_dimension(dataArray, nrSteps=100, plot=False):
    '''
    Function to estimate the correlation dimension
    '''
    nr_samples = dataArray.shape[0]
    nr_dimensions = dataArray.shape[1]
    
    # Compute the L_p norm between all pairs of points in the high dimensional space
    # Correlation dimension requires the computation of the L1 norm (p=1), i.e. |Xi-Xj|
    lp_distances = dist.squareform(dist.pdist(dataArray, p=1))
    #lp_distances = dist.pdist(dataArray, p=1) # Which one appropriate? It gives different fractal dims...
    
    # Normalize distances by their st. dev.?
    sd_dist = np.std(lp_distances)
    #lp_distances = lp_distances/sd_dist
    
    # Define range of radii for which to evaluate the correlation sum Cr
    strategyRadii = 'log'# 'log' or 'linear'
    
    if strategyRadii == 'linear':
        r_min = np.min(lp_distances)
        r_max = np.max(lp_distances)
        radii = np.linspace(r_min, r_max, nrSteps)
    if strategyRadii == 'log':
        r_min = np.percentile(lp_distances[lp_distances != 0],0.01)
        r_max = np.max(lp_distances)
        radiiLog = np.linspace(np.log10(r_min), np.log10(r_max), nrSteps)
        radii = 10**radiiLog
    
    Cr = []
    for r in radii:
        s = 1.0 / (nr_samples * (nr_samples-1)) * np.sum(lp_distances < r) # fraction
        #s = np.sum(lp_distances < r)/2 # count
        Cr.append(s)
    Cr = np.array(Cr)
    
    # Filter zeros from Cr
    nonzero = np.where(Cr != 0)
    radii = radii[nonzero]
    Cr = Cr[nonzero]
    
    # Put r and Cr in log units
    logRadii = np.log10(radii)
    logCr = np.log10(Cr)
    
    fittingStrategy = 2
    
    ### Strategy 1 for fitting the slope
    if fittingStrategy == 1:
        # Define a subrange for which the log(Cr)-log(r) curve is linear and good for fitting
        r_min_fit = np.percentile(lp_distances,5)
        r_max_fit = np.percentile(lp_distances,50)
        subsetIdxFitting = (radii >= r_min_fit) & (radii <= r_max_fit)
        
        # Compute correlation dimension as the linear slope in loglog plot
        reg = sp.polyfit(logRadii[subsetIdxFitting], logCr[subsetIdxFitting], 1)
        slope = reg[0]
        fractalDim = slope
        intercept = reg[1]
    
    ### Strategy 2 for fitting the slope
    if fittingStrategy == 2:
        nrPointsFitting = 20
        startIdx = 0
        maxSlope = 0.0
        while startIdx < (len(radii) - nrPointsFitting):
            subsetIdxFitting = np.arange(startIdx, startIdx+nrPointsFitting)
            reg = sp.polyfit(logRadii[subsetIdxFitting], logCr[subsetIdxFitting], 1)
            slope = reg[0]
            intercept = reg[1]
            if slope > maxSlope:
                maxSlope = slope
                maxIntercept = intercept
            startIdx = startIdx + 2
        # Get highest slope (largest fractal dimension estimation)
        slope = maxSlope
        fractalDim = slope
        intercept = maxIntercept
    
    ######## Plot fitting of correlation dimension
    if plot:
        fig = plt.figure()
        ax = fig.add_subplot(111)
        ax.plot(logRadii, logCr, 'b', linewidth=2)
        regFit = intercept + slope*logRadii
        plt.plot(logRadii, regFit, 'r', linewidth=2)
        
        plt.title('Correlation dimension estimation', fontsize=24)
        plt.xlabel('log(r)', fontsize=20)
        plt.ylabel('log(C(r))', fontsize=20)
        
        plt.text(0.05,0.95,'Sample size   = ' + str(nr_samples), transform=ax.transAxes, fontsize=16)
        plt.text(0.05,0.90,'Embedding dim = ' + str(nr_dimensions), transform=ax.transAxes, fontsize=16)
        plt.text(0.05,0.85,'Fractal dim   = ' + str(fmt2 % slope), transform=ax.transAxes, fontsize=16)
        plt.show()
        
        # plt.imshow(lp_distances)
        # plt.show()
    
    return(radii, Cr, fractalDim, intercept)

def logarithmic_r(min_n, max_n, factor):
	"""
	Creates a list of values by successively multiplying a minimum value min_n by
	a factor > 1 until a maximum value max_n is reached.

	Args:
		min_n (float): minimum value (must be < max_n)
		max_n (float): maximum value (must be > min_n)
		factor (float): factor used to increase min_n (must be > 1)

	Returns:
		list of floats: min_n, min_n * factor, min_n * factor^2, ... min_n * factor^i < max_n
	"""
	assert max_n > min_n
	assert factor > 1
	max_i = int(np.floor(np.log(1.0 * max_n / min_n) / np.log(factor)))
    
	return [min_n * (factor ** i) for i in range(max_i+1)]
    
def percentiles(array, percentiles):
    '''
    Function to compute a set of quantiles from an array
    '''
    nrPerc = len(percentiles)
    percentilesArray = []
    for p in range(0,nrPerc):
        perc = np.percentile(array,percentiles[p])
        percentilesArray.append(perc)
    percentilesArray = np.array(percentilesArray)
    return(percentilesArray)
    
def smooth_extrapolate_velocity_field(u, v, prvs, next, sigma):
    '''
    In development...
    '''
    nrRows = u.shape[0]
    nrCols = u.shape[1]
    nrGridPts = nrRows*nrCols
    
    mask = (prvs > 0) & (next > 0) 
    
    # Generate all grid coordinates
    idx = np.arange(0,nrRows)
    idxMat = np.tile(idx, [nrRows,1])
    idxMatMask = idxMat.copy()
    idxMatMask[mask != 1] = -999 
    
    idy = np.arange(0,nrCols)
    idyMat = np.tile(idy.T, [nrCols,1]).T
    idyMatMask = idyMat.copy()
    idyMatMask[mask != 1] = -999 
    
    allCoords = np.array([idxMat.ravel(),idyMat.ravel()]).T
    
    # Inputs
    trainingX = idxMatMask.ravel()
    trainingX = trainingX[trainingX == -999]
    trainingY = idyMatMask.ravel()
    trainingY = trainingY[trainingY == -999]
    
    # Outputs
    trainingU = u.ravel()
    trainingU = trainingU[trainingY == -999]
    trainingV = v.ravel()
    trainingV = trainingV[trainingV == -999]
    
    from scipy.interpolate import Rbf
    rbfi = Rbf(trainingX, trainingY, trainingU, epsilon = 10)
    uvec = rbfi(allCoords[:,0], allCoords[:,1])
    
    rbfi = Rbf(trainingX, trainingY, trainingV, epsilon = 10)
    vvec = rbfi(allCoords[:,0], allCoords[:,1])
    
    ugrid = uvec.reshape(nrRows,nrCols)
    vgrid = vvec.reshape(nrRows,nrCols)
    
    flow = np.dstack((ugrid,vgrid))

#### Methods to compute the anisotropy ####
def generate_data():
    data = np.zeros((200, 200), dtype=np.float)
    cov = np.array([[200, 100], [100, 200]])
    ij = np.random.multivariate_normal((100,100), cov, int(1e5))
    for i,j in ij:
        data[int(i), int(j)] += 1
    return data 

def _raw_moment(data, iord, jord):
    nrows, ncols = data.shape
    y, x = np.mgrid[:nrows, :ncols]
    data = data * x**iord * y**jord
    return data.sum()

def _intertial_axis(data):
    """Calculate the x-mean, y-mean, and cov matrix of an image."""
    data_sum = data.sum()
    m10 = _raw_moment(data, 1, 0)
    m01 = _raw_moment(data, 0, 1)
    x_bar = m10 / data_sum
    y_bar = m01 / data_sum
    u11 = (_raw_moment(data, 1, 1) - x_bar * m01) / data_sum
    u20 = (_raw_moment(data, 2, 0) - x_bar * m10) / data_sum
    u02 = (_raw_moment(data, 0, 2) - y_bar * m01) / data_sum
    cov = np.array([[u20, u11], [u11, u02]])
    return x_bar, y_bar, cov

def _make_lines(eigvals, eigvecs, mean, i):
        """Make lines a length of 2 stddev."""
        std = np.sqrt(eigvals[i])
        vec = 2 * std * eigvecs[:,i] / np.hypot(*eigvecs[:,i])
        x, y = np.vstack((mean-vec, mean, mean+vec)).T
        return x, y
        
def decompose_cov_plot_bars(x_bar, y_bar, cov, ax):
    """Plot bars with a length of 2 stddev along the principal axes."""
    mean = np.array([x_bar, y_bar])
    eigvals, eigvecs = np.linalg.eigh(cov)
    ax.plot(*_make_lines(eigvals, eigvecs, mean, 0), marker='o', color='white')
    ax.plot(*_make_lines(eigvals, eigvecs, mean, -1), marker='o', color='white')
    ax.axis('image')
    return(eigvals,eigvecs)

def plot_bars(x_bar, y_bar, eigvals, eigvecs, ax, colour='white'):
    """Plot bars with a length of 2 stddev along the principal axes."""
    mean = np.array([x_bar, y_bar])
    ax.plot(*_make_lines(eigvals, eigvecs, mean, 0), marker='o', color=colour)
    ax.plot(*_make_lines(eigvals, eigvecs, mean, -1), marker='o', color=colour)
    #ax.axis('image') # may give a weird displacement of axes...
########################

def update_mean(data, newSample):
    '''
    Algorithm to compute the online mean.
    '''
    oldMean = np.nanmean(data)
    n = np.sum(~np.isnan(data))
    
    n += 1
    # Contribution of the new sample to the old mean
    delta = newSample - oldMean 
    # Update of the old mean
    newMean += delta/n 

    if n < 2:
        return float('nan')
    else:
        return newMean

def wavelet_decomposition_2d(rainfield, wavelet = 'haar', nrLevels = None):
    nrRows = rainfield.shape[0]
    nrCols = rainfield.shape[1]

    if nrLevels == None:
        minDim = np.min([nrRows,nrRows])
        nrLevels = int(np.log2(minDim))
    # Perform wavelet decomposition
    w = pywt.Wavelet(wavelet)
    
    wavelet_coeff = []
    for level in range(0,nrLevels):
        # Decompose rainfield with wavelet
        cA, (cH, cV, cD) = pywt.dwt2(rainfield, wavelet)
        # Next rainfield to decompose is equal to the wavelet approximation
        rainfield = cA/2.0
        wavelet_coeff.append(rainfield)
    
    return(wavelet_coeff)

def generate_wavelet_coordinates(wavelet_coeff, originalImageShape, Xmin, Xmax, Ymin, Ymax, gridSpacing):
    
    nrScales = len(wavelet_coeff)
    # Generate coordinates of centers of wavelet coefficients
    xvecs = []
    yvecs = []
    for scale in range(0,nrScales):
        wc_fieldsize = np.array(wavelet_coeff[scale].shape)
        wc_boxsize = np.array(originalImageShape)/wc_fieldsize*gridSpacing
        gridX = np.arange(Xmin + wc_boxsize[1]/2,Xmax,wc_boxsize[1])
        gridY = np.flipud(np.arange(Ymin + wc_boxsize[0]/2,Ymax,wc_boxsize[0]))
        # print(wc_fieldsize, wc_boxsize)
        # print(Xmin, Xmax, gridX, gridY)
        xvecs.append(gridX)
        yvecs.append(gridY)
    
    return(xvecs, yvecs)
    
def generate_wavelet_noise(rainfield, wavelet='db4', nrLevels=6, level2perturb='all', nrMembers=1):
    '''
    First naive attempt to generate stochastic noise using wavelets
    '''
    fieldSize = rainfield.shape
    
    # Decompose rainfall field
    coeffsRain = pywt.wavedec2(rainfield, wavelet, level=nrLevels)
    
    stochasticEnsemble = []
    for member in range(0,nrMembers):
        # Generate and decompose noise field
        noisefield = np.random.randn(fieldSize[0],fieldSize[1])
        coeffsNoise = pywt.wavedec2(noisefield, wavelet, level=nrLevels)
        
        if level2perturb == 'all':
            levels2perturbList = np.arange(1,nrLevels).tolist()
        else:
            if type(level2perturb) == int:
                levels2perturbList = [level2perturb]
            elif type(level2perturb) == np.ndarray:
                levels2perturbList = level2perturb.to_list()
            elif type(level2perturb) == list:
                levels2perturbList = level2perturb
            else:
                print('List of elvels to perturb in generate_wavelet_noise is not in the right format.')
                sys.exit(0)
        
        # Multiply the wavelet coefficients of rainfall and noise fields at each level
        for level in levels2perturbList:
            # Get index of the level since data are organized in reversed order
            levelReversed = nrLevels - level
            
            # Get coefficients of noise field at given level
            coeffsNoise[levelReversed] = list(coeffsNoise[levelReversed])
            
            # Get coefficients of rain field at given level
            coeffsRain[levelReversed] = list(coeffsRain[levelReversed])
            
            # Perturb rain coefficients with noise coefficients
            rainCoeffLevel = np.array(coeffsRain[levelReversed][:])
            noiseCoeffLevel = np.array(coeffsNoise[levelReversed][:])
            
            for direction in range(0,2):
                # Compute z-scores
                rainCoeffLevel_zscores,mean,stdev = to_zscores(rainCoeffLevel[direction])
                noiseCoeffLevel_zscores,mean,stdev = to_zscores(noiseCoeffLevel[direction])
                
                #rainCoeffLevel_zscores = rainCoeffLevel[direction]
                #noiseCoeffLevel_zscores = noiseCoeffLevel[direction]
                
                #print(rainCoeffLevel_zscores,noiseCoeffLevel_zscores)
                coeffsRain[levelReversed][direction] = rainCoeffLevel[direction]*noiseCoeffLevel[direction] #rainCoeffLevel_zscores#*noiseCoeffLevel_zscores
            
            # print(coeffsRain[levelReversed])
            # sys.exit()
            # Replace the rain coefficients with the perturbed coefficients
            coeffsRain[levelReversed] = tuple(coeffsRain[levelReversed])
        
        # Reconstruct perturbed rain field
        stochasticRain = pywt.waverec2(coeffsRain, wavelet)
        
        # Append ensemble members
        stochasticEnsemble.append(stochasticRain)
    
    return stochasticEnsemble

def get_level_from_scale(resKM, scaleKM):
    if resKM == scaleKM:
        print('scaleKM should be larger than resKM in st.get_level_from_scale')
        sys.exit()
    elif isPower(scaleKM, resKM*2) == False:
        print('scaleKM should be a power of 2 in st.get_level_from_scale')
        sys.exit()
        
    for t in range(0,50):
        resKM = resKM*2
        if resKM == scaleKM:
            level = t
    return(level)

def isPower(n, base):
    return base**int(math.log(n, base)+.5)==n

    
def to_zscores(data, axis=None):

    if axis is None:
        mean = np.nanmean(data)
        stdev = np.nanstd(data)    
    else:
        mean = np.nanmean(data, axis=axis)
        stdev = np.nanstd(data, axis=axis)
    
    zscores = (data - mean)/stdev
    
    return zscores, mean, stdev
    
def from_zscores(data, mean, stdev):
    data = zscores*stdev + mean
    return data
    
def nanscatter(data, axis=0, minQ=16, maxQ=84):
    '''
    Function to compute the scatter score of Germann (simplified version without weighting).
    For a Gaussian distribution, the difference from the 84-16 quantiles is equal to +/- one standard deviation
    '''
    scatter = np.nanpercentile(data, maxQ, axis=axis) - np.nanpercentile(data, minQ, axis=axis)
    return scatter
    
def spherical_model(h, nugget, sill, range):
    c0 = nugget
    c1 = sill
    a = range
    
    spherical = np.where(h > a, c0 + c1, c0 + c1*(1.5*(h/a) - 0.5*(h/a)**3))
    return spherical

def exponential_model(h, nugget, sill, range):
    c0 = nugget
    c1 = sill
    a = range
    exponential = c0 + c1*(1-np.exp(-3*h/a))
    return exponential
    
def box_cox_transform(datain,Lambda):
    dataout = datain.copy()
    if Lambda==0:
        dataout = np.log(dataout)
    else:
        dataout = (dataout**Lambda - 1)/Lambda
    return dataout
    
def box_cox_transform_test_lambdas(datain,lambdas=[]):
    if len(lambdas)==0:
        lambdas = np.linspace(-1,1,11)
    data = []
    labels=[]
    sk=[]
    for l in lambdas:
        data_transf = box_cox_transform(datain,l)
        data_transf = (data_transf - np.mean(data_transf))/np.std(data_transf)
        data.append(data_transf)
        labels.append('{0:.1f}'.format(l))
        sk.append(stats.skew(data_transf)) # skewness
    
    bp = plt.boxplot(data,labels=labels)
    
    ylims = np.percentile(data,0.99)
    plt.title('Box-Cox transform')
    plt.xlabel('Lambdas')
    
    ymax = np.zeros(len(data))
    for i in range(len(data)):
        y = sk[i]
        x = i+1
        plt.plot(x, y,'ok',ms=5, markeredgecolor ='k')
        fliers = bp['fliers'][i].get_ydata()
        if len(fliers>0):
            ymax[i] = np.max(fliers)
    ylims = np.percentile(ymax,60)
    plt.ylim((-1*ylims,ylims))
    plt.show()
    
def ortho_rotation(lam, method='varimax',gamma=None, 
                    eps=1e-6, itermax=100): 
    """ 
    Return orthogal rotation matrix 

    TODO: - other types beyond  
    """ 
    if gamma == None: 
        if (method == 'varimax'): 
            gamma = 1.0 
        if (method == 'quartimax'): 
            gamma = 0.0 

    nrow, ncol = lam.shape
    R = np.eye(ncol) 
    var = 0 

    for i in range(itermax): 
        lam_rot = np.dot(lam, R) 
        tmp = np.diag(np.sum(lam_rot ** 2, axis=0)) / nrow * gamma 
        u, s, v = np.linalg.svd(np.dot(lam.T, lam_rot ** 3 - np.dot(lam_rot, tmp))) 
        R = np.dot(u, v) 
        var_new = np.sum(s) 
        if var_new < var * (1 + eps): 
            break 
        var = var_new 

    return R 


from numpy import eye, asarray, dot, sum, diag
from numpy.linalg import svd
def varimax(Phi, gamma = 1.0, q = 20, tol = 1e-6):
    p,k = Phi.shape
    R = eye(k)
    d=0
    for i in xrange(q):
        d_old = d
        Lambda = dot(Phi, R)
        u,s,vh = svd(dot(Phi.T,asarray(Lambda)**3 - (gamma/p) * dot(Lambda, diag(diag(dot(Lambda.T,Lambda))))))
        R = dot(u,vh)
        d = sum(s)
        if d_old!=0 and d/d_old < 1 + tol: break
    
    Phi_rot = dot(Phi, R)
    return(Phi_rot, R) 
