"""Models, yardsticks and evaluation. Every training run is tracked in MLflow.

sim, baselines            the trade simulator and blind rules (the yardsticks)
tune                      Ray Tune search of LightGBM settings (train days only)
train, register           v1 model; registry aliases champion / previous / candidate
evaluate                  v1 one-time score on the locked test days
micro_train, micro_evaluate   v2 model and its one-time forward test
sprint                    the pre-registered alpha-sprint trials
"""
