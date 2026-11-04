# Runs after air_lib.py and air_npe.py, which the scenario loads into the client agent's namespace
# first (each clientEval shares that namespace). Clears any earlier job and reports where the AIR is.
agent.air_job = None
result = {'task': air_task(), 'state': air_state()}
