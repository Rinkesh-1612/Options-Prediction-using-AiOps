"""Compatibility path. v2 registered model versions were saved with the class path
`optpred.micro_train.MicroModel`; unpickling them needs this name.
New code imports `optpred.models.micro_train`."""

from optpred.models.micro_train import MicroModel  # noqa: F401
