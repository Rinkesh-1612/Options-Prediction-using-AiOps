"""Compatibility path. MLflow registered model versions were saved with the class path
`optpred.serving_model.DirectionModel`; unpickling them needs this name. New code imports
`optpred.serving.serving_model`."""

from optpred.serving.serving_model import *  # noqa: F403
from optpred.serving.serving_model import DirectionModel  # noqa: F401
