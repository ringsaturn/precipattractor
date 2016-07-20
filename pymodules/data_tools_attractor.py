#!/usr/bin/env python
from __future__ import division
from __future__ import print_function

import sys

import numpy as np
import pandas as pd
import statsmodels.formula.api as sm
from statsmodels.nonparametric.api import KernelReg

from scipy import stats
import matplotlib.colors as colors

def to_dB(array, offset=0.01):
    '''
    Transform array to dB
    '''
    isList = isinstance(array, list)
    if isList == True:
        array = np.array(array)
    if offset != -1:
        dBarray = 10.0*np.log10(array + offset)
    else:
        dBarray = 10.0*np.log10(array)
        
    if isList == True:
        dBarray = dBarray.tolist()
    return(dBarray)

def get_column_list(list2D, columnNr):
    listColumn = [item[columnNr] for item in list2D]
    return(listColumn)

def get_variable_indices(subsetVariableNames, listVariableNames):
    nrVarTot = len(listVariableNames)
    nrVarSubset = len(subsetVariableNames)

    indices = []
    for item in range(0,nrVarSubset):
        var = subsetVariableNames[item]
        index = listVariableNames.index(var)
        indices.append(index)
    return(indices)

def get_reduced_extent(width, height, domainSizeX, domainSizeY):
    borderSizeX = (width - domainSizeX)/2
    borderSizeY = (height - domainSizeY)/2
    extent = (borderSizeX, borderSizeY, width-borderSizeX, height-borderSizeY) # left, upper, right, lower
    return(extent)
    
def extract_middle_domain_img(demImg, domainSizeX, domainSizeY):
    width, height = demImg.size
    extent = get_reduced_extent(width, height, domainSizeX, domainSizeY)
    demImgCropped = demImg.crop(extent)
    
    return(demImgCropped)

def extract_middle_domain(rainfield, domainSizeX, domainSizeY):
    borderSizeX = int((rainfield.shape[1] - domainSizeX)/2)
    borderSizeY = int((rainfield.shape[0] - domainSizeY)/2)
    mask = np.ones((rainfield.shape))
    mask[0:borderSizeY,:] = 0
    mask[borderSizeY+domainSizeY:,:] = 0
    mask[:,0:borderSizeX] = 0
    mask[:,borderSizeX+domainSizeX:] = 0
    
    rainfieldDomain = rainfield[mask==1].reshape(domainSizeY,domainSizeX)
    
    return(rainfieldDomain)

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
    
def rainrate2reflectivity(rainrate, A, b):
    zerosIdx = rainrate == 0
    rainIdx = rainrate > 0
    
    # Compute or set minimum reflectivity
    nrRainPixels = np.sum(rainIdx)
    if nrRainPixels >= 10:
        minRainRate = np.min(rainrate[rainIdx])
    else:
        minRainRate = 0.012 # 0.0115537519713
    minDBZ = 10.0*np.log10(A*minRainRate+b)
    
    # Compute reflectivity
    dBZ = -999.0*np.ones(rainrate.shape)
    dBZ[rainIdx] = 10.0*np.log10(A*rainrate[rainIdx]+b)
    
    # Replace zero rainrate by the minimum observed reflectivity
    dBZ[zerosIdx] = minDBZ
    
    return dBZ
    
def get_rainfall_lookuptable(noData):
    precipIdxFactor=71.5
    lut = np.zeros(256)
    for i in range(0,256):
        if (i < 2) or (i > 250 and i < 255):
            lut[i] = 0.0
        elif (i == 255):
            lut[i] = noData
        else:
            lut[i] = (10.**((i-(precipIdxFactor))/20.0)/316.0)**(0.6666667)
    
    return lut

def get_colorlist(type):
    if type == 'STEPS':
        color_list = ['cyan','deepskyblue','dodgerblue','blue','chartreuse','limegreen','green','darkgreen','yellow','gold','orange','red','magenta','darkmagenta']
        clevs = [0.1,0.25,0.4,0.63,1,1.6,2.5,4,6.3,10,16,25,40,63,100]
    if type == 'MeteoSwiss':
        pinkHex = '#%02x%02x%02x' % (232, 215, 242)
        redgreyHex = '#%02x%02x%02x' % (156, 126, 148)
        color_list = [pinkHex, redgreyHex, "#640064","#AF00AF","#DC00DC","#3232C8","#0064FF","#009696","#00C832",
        "#64FF00","#96FF00","#C8FF00","#FFFF00","#FFC800","#FFA000","#FF7D00","#E11900"] # light gray "#D3D3D3"
        clevs= [0,0.08,0.16,0.25,0.40,0.63,1,1.6,2.5,4,6.3,10,16,25,40,63,100,160]
        
    return(color_list, clevs)

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
    
def create_sparse_grid(gridSpacing, nrRows, nrCols):
    xSub = []
    ySub = []
    for i in range(0,nrRows):
        for j in range(0,nrCols):
            if ((i % gridSpacing) == 0) & ((j % gridSpacing) == 0):
                xSub.append(j)
                ySub.append(i)
                
    xSub = np.asarray(xSub)
    ySub = np.asarray(ySub)
    
    return(xSub, ySub)
    
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
    print(trainingX.shape)
    rbfi = Rbf(trainingX, trainingY, trainingU, epsilon = 10)
    uvec = rbfi(allCoords[:,0], allCoords[:,1])
    
    rbfi = Rbf(trainingX, trainingY, trainingV, epsilon = 10)
    vvec = rbfi(allCoords[:,0], allCoords[:,1])
    
    ugrid = uvec.reshape(nrRows,nrCols)
    vgrid = vvec.reshape(nrRows,nrCols)
    
    flow = np.dstack((ugrid,vgrid))
    print(flow.shape)