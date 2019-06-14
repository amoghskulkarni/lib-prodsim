

# Generic imports
import random

# SimPy related imports
from simpy import Event

class UnscheduledMaintenance:
    def __init__(self, unsched_id, proc, params):
        self.name = params['name']
        self.id = unsched_id
        self.duration_mean = params['duration_mean']
        self.duration_stddev = params['duration_stddev']
        self.mtbf = params['mtbf']

        # References to simulation and events
        self.process = proc
        self.logger = proc.procflow_sim.logger
        self.procflow_sim = proc.procflow_sim

        self.shift_start_event = proc.shift_start_event
        self.env = proc.procflow_sim.simpy_env

        # Remaining scheduled maintenance duration
        # (in case the scheduled maintenance activity gets preempted by end of the shift)
        self.remaining_duration = self.sample_duration()
        self.remaining_interarrival_time = self.sample_frequency()

        # The maintenance event to yield on
        self.maintenance_event = Event(self.env)
        self.maintenance_complete_event = Event(self.env)

    def maintenance_interrupt(self):
        while True:
            simtime_before_waiting_for_event = self.env.now

            interarrival_event = self.env.timeout(delay=self.remaining_interarrival_time,
                                                    value={'event': 'Unscheduled maintenance'})

            # Wait for random amount of time
            result = yield self.env.any_of([self.process.shift_end_event, interarrival_event])

            if len(result.events) == 1:
                if result.events[0].value['event'] == 'Shift end':
                    self.logger.debug("{}\t\t\t{}\t\t(UnscheduledMaintenance)\t\t\t{}\t\t(Process):\t\t\t"
                                        "Shift ended"
                                        .format(self.env.now, self.name, self.process.name))

                    # Get the simulation time after this has been triggered
                    simtime_after_waiting_for_event = self.env.now

                    self.remaining_interarrival_time -= (simtime_after_waiting_for_event
                                                            - simtime_before_waiting_for_event)

                    # Wait for the shift to start again
                    yield self.env.timeout(delay=self.process.shift_off_time)

                elif result.events[0].value['event'] == 'Unscheduled maintenance':
                    # Interrupt the process
                    self.logger.info(
                        "{}\t\t\t{}\t\t(UnscheduledMaintenance)\t\t\t{}\t\t(Process):\t\t\t"
                        "Interrupt #{} triggered"
                        .format(self.env.now, self.name, self.process.name, self.id, ))
                    self.maintenance_event.succeed(value={'event': "Interrupt", 'unsched_maint_id': self.id})

                    # Wait for maintenance to complete
                    yield self.maintenance_complete_event

                    # Resample the time between this and the next interrupt
                    self.remaining_interarrival_time = self.sample_frequency()

                    self.logger.debug(
                        "{}\t\t\t{}\t\t(UnscheduledMaintenance)\t\t\t{}\t\t(Process):\t\t\t"
                        "Interrupt #{} is complete, next one is @{}"
                        .format(self.env.now, self.name, self.process.name, self.id,
                                self.env.now + self.remaining_interarrival_time))
            else:
                self.logger.warning("{}\t\t\t{}\t\t(UnscheduledMaintenance)\t\t\t{}\t\t(Process):\t\t\t"
                                    "Multiple events ({})"
                                    .format(self.env.now, self.name, self.process.name, len(result.events)))

                for e in result.events:
                    if e.value['event'] == 'Shift end':
                        self.logger.debug("{}\t\t\t{}\t\t(UnscheduledMaintenance)\t\t\t{}\t\t(Process):\t\t\t"
                                            "Shift ended"
                                            .format(self.env.now, self.name, self.process.name))

                        # Get the simulation time after this has been triggered
                        simtime_after_waiting_for_event = self.env.now

                        self.remaining_interarrival_time -= (simtime_after_waiting_for_event
                                                                - simtime_before_waiting_for_event)

                        # Wait for the shift to start again
                        yield self.env.timeout(delay=self.process.shift_off_time)

                for e in result.events:
                    if e.value['event'] == 'Unscheduled maintenance':
                        # Interrupt the process
                        self.logger.info(
                            "{}\t\t\t{}\t\t(UnscheduledMaintenance)\t\t\t{}\t\t(Process):\t\t\t"
                            "Interrupt #{} triggered"
                            .format(self.env.now, self.name, self.process.name, self.id, ))
                        self.maintenance_event.succeed(value={'event': "Interrupt", 'unsched_maint_id': self.id})

                        # Wait for maintenance to complete
                        yield self.maintenance_complete_event

                        self.logger.debug(
                            "{}\t\t\t{}\t\t(UnscheduledMaintenance)\t\t\t{}\t\t(Process):\t\t\t"
                            "Interrupt #{} is complete, ready to sample the next one"
                            .format(self.env.now, self.name, self.process.name, self.id))

                        # Resample the time between this and the next interrupt
                        self.remaining_interarrival_time = self.sample_frequency()

    def sample_duration(self):
        duration_to_return = round(random.gauss(mu=self.duration_mean, sigma=self.duration_stddev), 4)
        if duration_to_return > 0:
            return duration_to_return
        else:
            # So that the simulator doesn't complain
            # TODO: Better handling of this edge case
            return 0.01

    def sample_frequency(self):
        interarrival_time_to_return = random.expovariate(1.0/self.mtbf)

        if interarrival_time_to_return > 0:
            return interarrival_time_to_return
        else:
            # So that the simulator doesn't complain
            # TODO: Better handling of this edge case
            return self.mtbf

class ScheduledMaintenance:
    def __init__(self, proc, params):
        self.name = params['name']
        self.duration_mean = params['duration_mean']
        self.duration_stddev = params['duration_stddev']
        self.no_of_parts = params['no_of_parts']
        self.counter = self.no_of_parts

        # Remaining scheduled maintenance duration
        # (in case the scheduled maintenance activity gets preempted by end of the shift)
        self.remaining_duration = self.sample_duration()

        # References to simulation
        self.process = proc
        self.logger = proc.procflow_sim.logger
        self.procflow_sim = proc.procflow_sim
        self.env = proc.procflow_sim.simpy_env

    def maintenance_interrupt(self):
        self.logger.info(
            "{}\t\t\t{}\t\t(ScheduledMaintenance)\t\t\t{}\t\t(Process):\t\t\tInterrupt triggered"
            .format(self.env.now, self.name, self.process.name))

        # Reset the counter
        self.counter = self.no_of_parts

    def sample_duration(self):
        duration_to_return = round(random.gauss(mu=self.duration_mean, sigma=self.duration_stddev), 4)
        if duration_to_return > 0:
            return duration_to_return
        else:
            # So that the simulator doesn't complain
            # TODO: Better handling of this edge case
            return 0.01
