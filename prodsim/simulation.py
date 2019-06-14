"""Module providing simulation class for simprod simulations 

The module provides definitions for class `Simulation`, the top-level object 
for running production line simulations. The module also uses the other 
submodules to create necessary objects like machines and buffers. 

Example
-------
TODO

Notes
-----
TODO

Attributes
----------
TODO

"""

# Generic imports 
from functools import wraps
from copy import deepcopy
import logging
import json
import sys

# SimPy related imports
from simpy import Environment, Event

# prodsim related imports
from objects import Machine, Storage

class Simulation:
    def __init__(self, params):
        """Returns a simulation object for a ProcessFlow element in MOCA

        Parameters
        ----------

        params: dict
            The parameters for the simulation object which are extracted from a simulation run in MOCA
        """
        # Name of the simulation object
        self.name = params['name']

        # Duration of the simulation
        self.duration = params['simulation_duration']

        # SimPy environment for the process flow simulation
        self.simpy_env = Environment()

        # Simulation termination event
        self.terminate_sim = Event(self.simpy_env)

        # Logger object
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(logging.DEBUG)

        # SimPy processes and buffers
        self.processes = []
        self.buffers = []

        # Extract the buffer paraemters from the parameters, and create an object for every buffer
        for procflow_buffer in params['buffers']:
            self.buffers.append(Storage(sim=self, buffer_params=procflow_buffer))

        # Extract the process parameters from the parameters, and create an object for every process
        for procflow_process in params['processes']:
            pf_process = Machine(sim=self, process_params=procflow_process)
            self.processes.append(pf_process)
            pf_process.install()

        # Get the list of jobs to be processed
        with open(params['schedulefile'], 'r') as f:
            self.schedulefile = json.load(f)

        self.num_jobs = len(self.schedulefile['jobs'])

        # Collect the traces of a simulation run (in the form of timeseries)
        self.simulation_traces = []

        # Collect the result of a simulation run (in the form of scalar stats)
        self.results = {}

        # Patch the original step() method of the simulator which processes the events with tracing stuff
        def get_wrapper(sim_obj, env_step):
            """
            Generates wrapper for env.step()
            :param sim_obj: The reference to simulation object
            :param env_step: Original step() function to be patched
            :return: The wrapper method
            """
            @wraps(env_step)
            def tracing_step():
                """
                Do the tracing thigs and after that call the original step() of the simulator
                :return:
                """
                if len(sim_obj.simpy_env._queue):
                    # do tracing things here for every event
                    t, prio, eid, event = sim_obj.simpy_env._queue[0]
                    trace = dict()
                    trace['process_metrics'] = dict()
                    trace['buffer_metrics'] = dict()
                    trace['timestamp'] = t
                    for pf_procs in sim_obj.processes:
                        trace['process_metrics'][pf_procs.name] = deepcopy(pf_procs.process_metrics)
                    for pf_buffer in sim_obj.buffers:
                        trace['buffer_metrics'][pf_buffer.name] = deepcopy(pf_buffer.buffer_metrics)
                    sim_obj.simulation_traces.append(trace)
                return env_step()
            return tracing_step

        self.simpy_env.step = get_wrapper(self, self.simpy_env.step)

    def simulate(self, text_log=True,  return_output=False, json_log=False, stdout_log=False):
        """Simulates the populated simulation object for the given amount of time

        Returns
        -------
        dict
            A dictionary containing the results and traces of the simulation that is run
        """
        # Install the handlers for logging
        if stdout_log:
            stdout_handler = logging.StreamHandler(stream=sys.stdout)
            stdout_handler.setLevel(logging.INFO)
            self.logger.addHandler(stdout_handler)

        if text_log:
            text_log_handler = logging.FileHandler(filename=self.name + '.log')
            text_log_handler.setLevel(logging.DEBUG)
            self.logger.addHandler(text_log_handler)

        # Separator in the log file
        self.logger.debug('*' * 50)

        # Simulate the SimPy object
        ret = self.simpy_env.run(until=self.simpy_env.any_of([self.simpy_env.timeout(self.duration),
                                                             self.terminate_sim]))

        # Return the results
        sim_output = {'results': self.results, 'traces': self.simulation_traces}

        if json_log:
            import json
            with open(self.name + '_traces.json', 'w') as json_file:
                json_contents = json.dumps(self.simulation_traces)
                json_file.write(json_contents)

        if return_output:
            return sim_output
