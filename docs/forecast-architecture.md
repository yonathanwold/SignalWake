# Forecast boundary (future work)

SIGNALWAKE V2 does not ship a current prediction or outage forecast. Any
future forecast must be a separate `FORECAST` classification and must never be
mixed into source observations, infrastructure reference geometry, or derived
exposure assessments.

The smallest defensible candidate is a transparent baseline family: persistence
and climatology first, followed by a calibrated logistic or Poisson model only
when a source-backed label and an explicit feature window exist. Every output
would include a model version, training/data cutoff, horizon, feature packet,
and validation run. Evaluation would use temporal backtests and report Brier
score and calibration error for probabilities, precision/recall for selected
thresholds, and comparisons with the baselines. No forecast is currently
validated or shown as an operational claim.
