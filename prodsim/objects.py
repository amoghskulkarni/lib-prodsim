"""Module providing machine and buffer classes for simprod simulations 

The module provides definitions for for class `Machine` and `Storage`. 

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
from enum import Enum
import random

# SimPy related imports
from simpy import Event, Store

# prodsim related imports
from interruptions import UnscheduledMaintenance, ScheduledMaintenance

class Machine:
    class MachineState(Enum):
        WAITING_FOR_INPUT = 1
        ACTIVE = 2
        BLOCKED_ON_OUTPUT = 3
        DOWN_FOR_SCHEDULED_MAINTENANCE = 4
        DOWN_FOR_UNSCHEDULED_MAINTENANCE = 5

    def __init__(self, sim, process_params):
        # Name of the process object
        self.name = process_params['name']
        self.cycle_time = process_params['cycle_time']
        self.shift_on_time = process_params['shift_on_time']
        self.shift_off_time = process_params['shift_off_time']

        # Maintain remaining cycle time (in case the process gets interrupted while producing a part)
        self.remaining_cycle_time = self.cycle_time

        # Unscheduled maintenance to be processed
        self.unsched_maintenance_to_be_processed = None

        # The parent simulation object
        self.procflow_sim = sim
        self.env = sim.simpy_env

        # States of the process
        self.process_state = self.MachineState.WAITING_FOR_INPUT

        # Store the reference of upstream buffer
        # TODO: Implement multiple upstream buffers
        self.upstream_buffer = None
        for bf in sim.buffers:
            if bf.name == process_params['upstream_buffer']:
                self.upstream_buffer = bf
                # Save the reverse reference
                self.upstream_buffer.downstream_process = self

        # Store the reference of downstream buffer
        # TODO: Implement multiple downstream buffers
        self.downstream_buffer = None
        for bf in sim.buffers:
            if bf.name == process_params['downstream_buffer']:
                self.downstream_buffer = bf
                # Save the reverse reference
                self.downstream_buffer.upstream_process = self

        # Process state variables
        self.process_metrics = {
            'parts_produced': 0,
            'up_time': 0,
            'scheduled_down_time': 0,
            'unscheduled_down_time': 0,
            'blocked_for': 0,
            'starved_for': 0
        }

        # Process events
        self.shift_end_event = Event(sim.simpy_env)
        self.shift_start_event = Event(sim.simpy_env)

        # Part ID placeholder
        self.part_id = 0

        # Job ID placeholders
        self.job_id = -1
        self.current_job = None

        # Process maintenances
        self.unscheduled_maintenances = []
        self.scheduled_maintenances = []

        # Maintenance objects
        maintenance_id = 0
        for unscheduled_maintenance in process_params['unscheduled_maintenances']:
            self.unscheduled_maintenances.append(UnscheduledMaintenance(maintenance_id,
                                                                        self,
                                                                        unscheduled_maintenance))
            maintenance_id += 1

        for scheduled_maintenance in process_params['scheduled_maintenances']:
            self.scheduled_maintenances.append(ScheduledMaintenance(self,
                                                                    scheduled_maintenance))

        # Logger object
        self.logger = self.procflow_sim.logger

    def business_logic(self):
        # Infinite loop
        while True:
            if self.process_state == self.MachineState.WAITING_FOR_INPUT:
                if self.upstream_buffer is not None:
                    # Get the timestamp before procurement
                    simtime_before_procurement = self.env.now

                    # Retrieve the raw material from the upstream buffer
                    part_procured_event = self.upstream_buffer.buffer.get()

                    # Wait for procurement as well as shift end,
                    # If the shift ends, don't change the state to ACTIVE
                    result = yield self.env.any_of([self.shift_end_event, part_procured_event])

                    if len(result.events) == 1:
                        if result.events[0].value is not None:
                            if result.events[0].value['event'] == 'Shift end':
                                self.logger.debug(
                                    "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tShift ended"
                                    .format(self.env.now, '<no name>', self.name))

                                # Get the current timestamp (the process is still waiting for the part)
                                simtime_after_procurement = self.env.now

                                # Update the process metric
                                self.process_metrics['starved_for'] += (simtime_after_procurement
                                                                        - simtime_before_procurement)

                                # Wait for the shift to start again
                                yield self.env.timeout(delay=self.shift_off_time)

                            elif result.events[0].value['event'] == 'Part stored':
                                # Got the part we were waiting for, change the state
                                self.process_state = self.MachineState.ACTIVE

                                retreived_part_id = result.events[0].value['ID']
                                self.current_job = result.events[0].value['job']
                                self.part_id = self.current_job['id']
                                self.remaining_cycle_time = round(random.gauss(mu=self.current_job[self.name]['mean'],
                                                                               sigma=self.current_job[self.name]['stddev']),
                                                                    4)

                                self.logger.info(
                                    "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tPart {} retreived "
                                    "from {} buffer"
                                    .format(self.env.now, '<no name>', self.name, retreived_part_id,
                                            self.upstream_buffer.name))

                                # Update the usage counter of the upstream buffer (UGLY)
                                self.upstream_buffer.buffer_metrics['usage'] -= 1

                                # Get the current timestamp and update the metric
                                simtime_after_procurement = self.env.now
                                self.process_metrics['starved_for'] += (simtime_after_procurement
                                                                        - simtime_before_procurement)
                    else:
                        self.logger.warning("{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\t"
                                            "Multiple events ({}) in state {}"
                                            .format(self.env.now, '<no name>', self.name, len(result.events),
                                                    self.process_state))

                        for e in result.events:
                            if e.value['event'] == 'Shift end':
                                self.logger.warning(
                                    "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tShift ended"
                                    .format(self.env.now, '<no name>', self.name))

                                # Get the current timestamp (the process is still waiting for the part)
                                simtime_after_procurement = self.env.now

                                # Update the process metric
                                self.process_metrics['starved_for'] += (simtime_after_procurement
                                                                        - simtime_before_procurement)

                                # Wait for the shift to start again
                                yield self.env.timeout(delay=self.shift_off_time)
                else:
                    # If there is no upstream buffer
                    self.process_state = self.MachineState.ACTIVE

                    # Get the current job
                    self.job_id += 1
                    if self.job_id > self.procflow_sim.num_jobs - 1:
                        yield self.procflow_sim.terminate_sim    # Yield indefinitely
                    else:
                        self.current_job = self.procflow_sim.schedulefile['jobs'][self.job_id]
                        self.part_id = self.current_job['id']
                        self.remaining_cycle_time = round(random.gauss(mu=self.current_job[self.name]['mean'],
                                                                       sigma=self.current_job[self.name]['stddev']),
                                                            4)

            elif self.process_state == self.MachineState.ACTIVE:
                # Get the timestamp before the production starts
                simtime_before_starting_production = self.env.now

                # Create an event instance to simulate the process
                production_complete_event = self.procflow_sim.simpy_env.timeout(delay=self.remaining_cycle_time,
                                                                                value={'event': 'Production complete'})

                # Wait for the production to get complete, or shift end or unscheduled maintenance interrupt
                events_to_wait_on = []
                for unscheduled_maintenance in self.unscheduled_maintenances:
                    events_to_wait_on.append(unscheduled_maintenance.maintenance_event)
                events_to_wait_on.append(self.shift_end_event)
                events_to_wait_on.append(production_complete_event)

                # Wait for the event that will occur first in the above list
                result = yield self.env.any_of(events_to_wait_on)

                if len(result.events) == 1:
                    if result.events[0].value is not None:
                        # Get the current timestamp (the process is still waiting for the part)
                        simtime_after_finishing_production = self.env.now
                        time_delta = simtime_after_finishing_production - simtime_before_starting_production

                        # Update the process metric
                        self.process_metrics['up_time'] += time_delta

                        if result.events[0].value['event'] == 'Shift end':
                            self.logger.debug(
                                "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tShift ended"
                                .format(self.env.now, '<no name>', self.name))

                            # Change the remaining cycle time for the next time
                            self.remaining_cycle_time -= time_delta

                            # Just a sanity check
                            if self.remaining_cycle_time < 0:
                                self.logger.error(
                                    "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tNegative cycle time"
                                    .format(self.env.now, '<no name>', self.name))
                                raise ValueError("Negative cycle time! Bug in the business logic!")

                            # Wait for the shift to start again
                            yield self.env.timeout(delay=self.shift_off_time)

                        elif result.events[0].value['event'] == 'Production complete':
                            # Completed the production, change the state
                            self.process_state = self.MachineState.BLOCKED_ON_OUTPUT

                            self.logger.info(
                                "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tProduction of "
                                "Part {} complete"
                                .format(self.env.now, '<no name>', self.name, self.part_id))

                            # Increment part produced counter
                            self.process_metrics['parts_produced'] += 1

                        elif result.events[0].value['event'] == 'Interrupt':
                            # Got interrupted, change the state
                            self.process_state = self.MachineState.DOWN_FOR_UNSCHEDULED_MAINTENANCE

                            trigger_id = result.events[0].value['unsched_maint_id']
                            self.logger.debug(
                                "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tInterrupted by interrupt #{}"
                                .format(self.env.now, '<no name>', self.name, trigger_id))

                            # Which unscheduled maintenance to be processed?
                            self.unsched_maintenance_to_be_processed = trigger_id
                else:
                    unscheduled_maintenance_needed = False

                    # Specially handle the occurrence of multiple interrupts in the same step
                    self.logger.warning("{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\t"
                                        "Multiple events ({}) in state {}"
                                        .format(self.env.now, '<no name>', self.name, len(result.events),
                                                self.process_state))

                    # Get the current timestamp (the process is still waiting for the part)
                    simtime_after_finishing_production = self.env.now
                    time_delta = simtime_after_finishing_production - simtime_before_starting_production

                    # Update the process metric
                    self.process_metrics['up_time'] += time_delta

                    # First, serve the shift interrupt
                    # (underlying assumption being this time parameter is dominant over the other time parameters)
                    for e in result.events:
                        if e.value['event'] == 'Shift end':
                            self.logger.warning(
                                "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tShift ended"
                                .format(self.env.now, '<no name>', self.name))

                            # Change the remaining cycle time for the next time
                            self.remaining_cycle_time -= time_delta

                            # Just a sanity check
                            if self.remaining_cycle_time < 0:
                                self.logger.error(
                                    "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tNegative cycle time"
                                    .format(self.env.now, '<no name>', self.name))
                                raise ValueError("Negative cycle time! Bug in the business logic!")

                            # Wait for the shift to start again
                            yield self.env.timeout(delay=self.shift_off_time)

                    # Then, check for the unscheduled interrupts
                    for e in result.events:
                        if e.value['event'] == 'Interrupt':
                            unscheduled_maintenance_needed = True

                            # Got interrupted, change the state
                            self.process_state = self.MachineState.DOWN_FOR_UNSCHEDULED_MAINTENANCE

                            trigger_id = result.events[0].value['unsched_maint_id']

                            self.logger.warning(
                                "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tInterrupted by interrupt #{}"
                                .format(self.env.now, '<no name>', self.name, trigger_id))

                            # Which unscheduled maintenance to be processed?
                            self.unsched_maintenance_to_be_processed = trigger_id

                    if not unscheduled_maintenance_needed:
                        for e in result.events:
                            if e.value['event'] == 'Production complete':
                                # Completed the production, change the state
                                self.process_state = self.MachineState.BLOCKED_ON_OUTPUT

                                self.logger.info(
                                    "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tProduction of "
                                    "Part {} complete"
                                    .format(self.env.now, '<no name>', self.name, self.part_id))

                                # Increment part produced counter
                                self.process_metrics['parts_produced'] += 1

            elif self.process_state == self.MachineState.BLOCKED_ON_OUTPUT:
                # Store the finished product in the downstream buffer (if any)
                if self.downstream_buffer is not None:
                    simtime_before_storing = self.env.now

                    # Store the finished part in the downstream buffer
                    part_stored_event = self.downstream_buffer.buffer.put({'event': 'Part stored',
                                                                           'ID': self.part_id,
                                                                           'job': self.current_job})

                    # Wait on both, part stored and shift end events
                    # Because while you are waiting, the shift can end
                    result = yield self.env.any_of([part_stored_event, self.shift_end_event])

                    # Get the current timestamp
                    simtime_after_storing = self.env.now
                    time_delta = simtime_after_storing - simtime_before_storing

                    # Update the process metric
                    self.process_metrics['blocked_for'] += time_delta

                    if len(result.events) == 1:
                        if result.events[0].value is not None and result.events[0].value['event'] == 'Shift end':
                                self.logger.debug(
                                    "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tShift ended"
                                    .format(self.env.now, '<no name>', self.name))

                                # Wait for the shift to start again
                                yield self.env.timeout(delay=self.shift_off_time)

                        elif result.events[0].value is None and result.events[0].item['event'] == 'Part stored':
                            # Stored the part, change the state
                            self.process_state = self.MachineState.WAITING_FOR_INPUT

                            self.logger.info(
                                "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tPart {} stored "
                                "in {} buffer"
                                .format(self.env.now, '<no name>', self.name, self.part_id,
                                        self.downstream_buffer.name))

                            # Update the usage counter of the downstream buffer (UGLY)
                            self.downstream_buffer.buffer_metrics['usage'] += 1

                            # Reset the remaining cycle time for the next part
                            self.remaining_cycle_time = self.cycle_time
                    else:
                        self.logger.warning("{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\t"
                                            "Multiple events ({}) in state {}"
                                            .format(self.env.now, '<no name>', self.name, len(result.events),
                                                    self.process_state))

                        for e in result.events:
                            if e.value['event'] == 'Shift end':
                                self.logger.warning(
                                    "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tShift ended"
                                    .format(self.env.now, '<no name>', self.name))

                                # Wait for the shift to start again
                                yield self.env.timeout(delay=self.shift_off_time)

                        # The shift have started again
                        # Stored the part, change the state
                        self.process_state = self.MachineState.WAITING_FOR_INPUT

                        self.logger.warning(
                            "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tPart {} stored "
                            "in {} buffer"
                                .format(self.env.now, '<no name>', self.name, self.part_id,
                                        self.downstream_buffer.name))

                        # Update the usage counter of the downstream buffer (UGLY)
                        self.downstream_buffer.buffer_metrics['usage'] += 1

                        # Reset the remaining cycle time for the next part
                        self.remaining_cycle_time = self.cycle_time

                else:
                    # If there is no downstream buffer
                    self.process_state = self.MachineState.WAITING_FOR_INPUT

                    # Reset the remaining cycle time for the next part
                    self.remaining_cycle_time = self.cycle_time

                    if self.current_job['id'] == self.procflow_sim.num_jobs - 1:
                        self.procflow_sim.results['sim_end_time'] = self.env.now
                        self.procflow_sim.terminate_sim.succeed()

                # Execute scheduled maintenance (if any)
                for sched_maintenance in self.scheduled_maintenances:
                    sched_maintenance.counter -= 1
                for sched_maintenance in self.scheduled_maintenances:
                    if sched_maintenance.counter == 0:
                        # Time for a scheduled maintenance, change the state
                        self.process_state = self.MachineState.DOWN_FOR_SCHEDULED_MAINTENANCE

            elif self.process_state == self.MachineState.DOWN_FOR_SCHEDULED_MAINTENANCE:
                # Execute scheduled maintenance (if any)
                # (Processes all of the scheduled maintenances that are expired)
                for sched_maintenance in self.scheduled_maintenances:
                    if sched_maintenance.counter == 0:
                        # Resets the part counter internal to the maintenance interrupt object
                        sched_maintenance.maintenance_interrupt()

                        # Get the timestamp before going for the scheduled maintenance
                        simtime_before_starting_sched_maintenance = self.env.now

                        self.logger.info(
                            "{}\t\t\t{}\t\t(ScheduledMaintenance)\t\t\t{}\t\t(Process):\t\t\t"
                            "Scheduled maintenance started"
                            .format(self.env.now, sched_maintenance.name, self.name))

                        # Wait for the scheduled maintenance duration and shift end
                        sched_maintenance_event = self.env.timeout(delay=sched_maintenance.remaining_duration,
                                                                   value={'event': 'Scheduled maintenance over'})

                        result = yield self.env.any_of([sched_maintenance_event, self.shift_end_event])

                        # Get the current timestamp (the process is still waiting for the part)
                        simtime_after_stopping_sched_maintenance = self.env.now

                        time_delta = simtime_after_stopping_sched_maintenance \
                            - simtime_before_starting_sched_maintenance

                        # Update the process metric
                        self.process_metrics['scheduled_down_time'] += time_delta

                        if len(result.events) == 1:
                            if result.events[0].value is not None:
                                if result.events[0].value['event'] == 'Shift end':
                                    self.logger.debug(
                                        "{}\t\t\t{}\t\t(ScheduledMaintenance)\t\t\t{}\t\t(Process):\t\t\tShift ended"
                                        .format(self.env.now, sched_maintenance.name, self.name))

                                    sched_maintenance.remaining_duration -= time_delta

                                    # Wait for the shift to start again
                                    yield self.env.timeout(delay=self.shift_off_time)

                                elif result.events[0].value['event'] == 'Scheduled maintenance over':
                                    self.logger.info(
                                        "{}\t\t\t{}\t\t(ScheduledMaintenance)\t\t\t{}\t\t(Process):\t\t\t"
                                        "Scheduled maintenance over"
                                        .format(self.env.now, sched_maintenance.name, self.name))

                                    # Sample the duration of the interrupt
                                    sched_maintenance.remaining_duration = sched_maintenance.sample_duration()

                        else:
                            self.logger.warning("{}\t\t\t{}\t\t(ScheduledMaintenance)\t\t\t{}\t\t(Process):\t\t\t"
                                                "Multiple events ({})"
                                                .format(self.env.now, sched_maintenance.name, self.name,
                                                        len(result.events)))

                            for e in result.events:
                                if e.value['event'] == 'Shift end':
                                    self.logger.warning(
                                        "{}\t\t\t{}\t\t(ScheduledMaintenance)\t\t\t{}\t\t(Process):\t\t\tShift ended"
                                        .format(self.env.now, sched_maintenance.name, self.name))

                                    # Wait for the shift to start again
                                    yield self.env.timeout(delay=self.shift_off_time)

                            for e in result.events:
                                if e.value['event'] == 'Scheduled maintenance over':
                                    self.logger.warning(
                                        "{}\t\t\t{}\t\t(ScheduledMaintenance)\t\t\t{}\t\t(Process):\t\t\t"
                                        "Scheduled maintenance over"
                                        .format(self.env.now, sched_maintenance.name, self.name))

                                    # Sample the duration of the interrupt
                                    sched_maintenance.remaining_duration = sched_maintenance.sample_duration()

                # Go to the initial state in process state machine
                self.process_state = self.MachineState.WAITING_FOR_INPUT

                # Reset the remaining cycle time for the next part
                self.remaining_cycle_time = self.cycle_time

            elif self.process_state == self.MachineState.DOWN_FOR_UNSCHEDULED_MAINTENANCE:
                # First, a sanity check
                if self.unsched_maintenance_to_be_processed is not None:
                    # Get the reference of the interrupt object
                    unsched_maintenance = self.unscheduled_maintenances[self.unsched_maintenance_to_be_processed]

                    # Get the timestamp before going for the unscheduled maintenance
                    simtime_before_starting_unsched_maintenance = self.env.now

                    self.logger.info(
                        "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\t"
                        "Unscheduled maintenance started"
                        .format(self.env.now, unsched_maintenance.name, self.name))

                    # Wait for the scheduled maintenance duration and shift end
                    unsched_maintenance_event = self.env.timeout(delay=unsched_maintenance.remaining_duration,
                                                                 value={'event': 'Unscheduled maintenance over'})

                    result = yield self.env.any_of([unsched_maintenance_event, self.shift_end_event])

                    # Get the current timestamp (the process is still waiting for the part)
                    simtime_after_stopping_unsched_maintenance = self.env.now

                    time_delta = simtime_after_stopping_unsched_maintenance \
                        - simtime_before_starting_unsched_maintenance

                    # Update the process metric
                    self.process_metrics['unscheduled_down_time'] += time_delta

                    if len(result.events) == 1:
                        if result.events[0].value is not None:
                            if result.events[0].value['event'] == 'Shift end':
                                self.logger.debug(
                                    "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tShift ended"
                                    .format(self.env.now, unsched_maintenance.name, self.name))

                                unsched_maintenance.remaining_duration -= time_delta

                                # Wait for the shift to start again
                                yield self.env.timeout(delay=self.shift_off_time)

                            elif result.events[0].value['event'] == 'Unscheduled maintenance over':
                                self.logger.info(
                                    "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\t"
                                    "Unscheduled maintenance over"
                                    .format(self.env.now, unsched_maintenance.name, self.name))

                                # Sample the duration of the interrupt
                                unsched_maintenance.remaining_duration = unsched_maintenance.sample_duration()

                                # Reset the reference to None
                                self.unsched_maintenance_to_be_processed = None

                                # Go to the initial state in process state machine
                                self.process_state = self.MachineState.WAITING_FOR_INPUT

                                # Reset the remaining cycle time for the next part
                                self.remaining_cycle_time = self.cycle_time

                                # Resume the process which produces these unscheduled events
                                unsched_maintenance.maintenance_complete_event.succeed(
                                    value={'event': 'Resume', 'unsched_maint_id': unsched_maintenance.id})

                                # Then, replace the Event objects
                                unsched_maintenance.maintenance_event = Event(self.env)
                                unsched_maintenance.maintenance_complete_event = Event(self.env)

                                # FIXME: Simulation termination condition (UGLY)
                                if self.downstream_buffer is None and self.current_job['id'] == self.procflow_sim.num_jobs - 1:
                                    self.procflow_sim.terminate_sim.succeed()
                    else:
                        self.logger.warning("{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\t"
                                            "Multiple events ({})"
                                            .format(self.env.now, unsched_maintenance.name, self.name,
                                                    len(result.events)))

                        for e in result.events:
                            if e.value['event'] == 'Shift end':
                                self.logger.warning(
                                    "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\tShift ended"
                                    .format(self.env.now, unsched_maintenance.name, self.name))

                                unsched_maintenance.remaining_duration -= time_delta

                                # Wait for the shift to start again
                                yield self.env.timeout(delay=self.shift_off_time)

                        for e in result.events:
                            if e.value['event'] == 'Unscheduled maintenance over':
                                self.logger.warning(
                                    "{}\t\t\t{}\t\t(BusinessLogic)\t\t\t{}\t\t(Process):\t\t\t"
                                    "Unscheduled maintenance over"
                                    .format(self.env.now, unsched_maintenance.name, self.name))

                                # Sample the duration of the interrupt
                                unsched_maintenance.remaining_duration = unsched_maintenance.sample_duration()

                                # Reset the reference to None
                                self.unsched_maintenance_to_be_processed = None

                                # Go to the initial state in process state machine
                                self.process_state = self.MachineState.WAITING_FOR_INPUT

                                # Reset the remaining cycle time for the next part
                                self.remaining_cycle_time = self.cycle_time

                                # Resume the process which produces these unscheduled events
                                unsched_maintenance.maintenance_complete_event.succeed(
                                    value={'event': 'Resume', 'unsched_maint_id': unsched_maintenance.id})

                                # Then, replace the Event objects
                                unsched_maintenance.maintenance_event = Event(self.env)
                                unsched_maintenance.maintenance_complete_event = Event(self.env)

    def shift_controller(self):
        # Reference to SimPy environment
        env = self.procflow_sim.simpy_env
        while True:
            # Wait for shift on time
            yield env.timeout(self.shift_on_time)

            # End the shift (interrupt the process)
            self.logger.info(
                "{}\t\t\t{}\t\t(ShiftController)\t\t\t{}\t\t(Process):\t\t\t"
                "Shift end triggered"
                .format(self.env.now, '<no name>', self.name))
            self.shift_end_event.succeed(value={'event': "Shift end"})
            self.shift_end_event = Event(env)

            # Wait for shift off time
            yield env.timeout(self.shift_off_time)

            # Start the shift (interrupt the process)
            self.logger.info(
                "{}\t\t\t{}\t\t(ShiftController)\t\t\t{}\t\t(Process):\t\t\t"
                "Shift start triggered"
                .format(self.env.now, '<no name>', self.name))
            self.shift_start_event.succeed(value={'event': "Shift start"})
            self.shift_start_event = Event(env)

    def install(self):
        # Reference to SimPy environment
        env = self.procflow_sim.simpy_env

        # Shift controller for the process
        env.process(self.shift_controller())

        # Unscheduled maintenance
        for unscheduled_maintenance in self.unscheduled_maintenances:
            env.process(unscheduled_maintenance.maintenance_interrupt())

        # The underlying process model
        env.process(self.business_logic())

class Storage:
    def __init__(self, sim, buffer_params):
        """Returns a buffer object for a Buffer object in MOCA

        :param sim: Reference to DES simulation object
        :param buffer_params: Dictionary of parameters
        """
        # Name and size of the buffer object
        self.name = buffer_params['name']
        self.size = buffer_params['size']

        # The parent simulation object
        self.procflow_sim = sim

        # References to upstream and downstream processes
        self.upstream_process = None
        self.downstream_process = None

        # Internal buffer
        self.buffer = Store(self.procflow_sim.simpy_env, capacity=self.size)

        # Buffer state variables
        self.buffer_metrics = {
            'usage': 0
        }

    def store(self, part):
        """Stores the given part in the buffer

        :param part: Part object to be stored
        :return: The event of the buffer
        """
        yield self.buffer.put(part)

    def retrieve(self):
        """Retrieves the first part from the buffer

        :return: The part from the buffer (or waits for the buffer till a part arrives)
        """
        yield self.buffer.get()
