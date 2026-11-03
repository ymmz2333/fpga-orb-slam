"""The retained numerical gate, compatible with the older Vitis AI SciPy."""
import numpy as np
from scipy.stats import spearmanr


def evaluate(reference,output):
    reference=np.asarray(reference,np.float64).ravel();output=np.asarray(output,np.float64).ravel()
    if reference.shape!=output.shape or not np.isfinite(output).all() or not np.isfinite(reference).all():raise ValueError('Invalid output/reference')
    span=float(np.quantile(reference,.95)-np.quantile(reference,.05))
    if span<=1e-8:raise ValueError('Degenerate floating reference')
    rho=float(spearmanr(reference,output)[0])
    if not np.isfinite(rho):raise ValueError('Degenerate prediction ranks')
    return {'normalized_rmse':float(np.sqrt(np.mean((output-reference)**2))/span),'spearman':rho,
            'normalization':'RMSE / (reference P95 - P05), no output alignment'}
