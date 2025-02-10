from djitellopy import tello
import pygame
import logging
from dataclasses import dataclass
from typing import Tuple, Dict
import time

@dataclass
class DroneConfig:
    """Configuration settings for drone control"""
    min_battery_level: int = 10
    speed_max: int = 250
    countersteer: int = 20
    speed_increase: int = 10
    speed_falloff: int = 5
    takeoff_cooldown: float = 3.0  # Seconds between takeoff/land commands

@dataclass
class ControlConfig:
    """Keyboard control mapping configuration"""
    movement_controls: Dict[str, Dict[str, str]] = None
    speed_controls: Dict[str, float] = None

    def __post_init__(self):
        if self.movement_controls is None:
            self.movement_controls = {
                'lr': {'pos': 'd', 'neg': 'a'},      # Left/Right
                'fb': {'pos': 'w', 'neg': 's'},      # Forward/Back
                'ud': {'pos': 'UP', 'neg': 'DOWN'},  # Up/Down
                'yv': {'pos': 'RIGHT', 'neg': 'LEFT'}# Yaw
            }
        if self.speed_controls is None:
            self.speed_controls = {
                'LSHIFT': 1.0,    # 100% speed
                'LCTRL': 0.5,     # 50% speed
                'default': 0.75   # 75% speed
            }

class DroneController:
    """Handles keyboard-based drone control"""
    def __init__(self, drone_config: DroneConfig = DroneConfig(),
                 control_config: ControlConfig = ControlConfig()):
        self.config = drone_config
        self.controls = control_config
        self.speeds = {'lr': 0, 'fb': 0, 'ud': 0, 'yv': 0}
        self.in_flight = False
        self.last_takeoff_time = 0
        self.logger = logging.getLogger(__name__)

    def initialize_drone(self) -> tello.Tello:
        """
        Initialize and configure the drone.
        
        Returns:
            tello.Tello: Configured drone instance
            
        Raises:
            Exception: If battery level is too low or connection fails
        """
        try:
            drone = tello.Tello()
            drone.connect()

            battery = drone.get_battery()
            self.logger.info(f"Battery level: {battery}%")

            if battery < self.config.min_battery_level:
                raise Exception(f'Battery level too low: {battery}%')

            drone.LOGGER.setLevel(logging.WARNING)
            drone.streamon()
            
            # Sync our in_flight state with actual drone state
            self.in_flight = drone.is_flying()
            self.logger.info("Drone initialized successfully")
            return drone

        except Exception as e:
            self.logger.error(f"Failed to initialize drone: {e}")
            raise

    def get_key(self, key_name: str) -> bool:
        """Check if a specific key is pressed"""
        try:
            key_input = pygame.key.get_pressed()
            my_key = getattr(pygame, f'K_{key_name}')
            return key_input[my_key]
        except AttributeError:
            self.logger.warning(f"Invalid key name: {key_name}")
            return False

    def get_target_speed(self) -> int:
        """Calculate target speed based on modifier keys"""
        for key, multiplier in self.controls.speed_controls.items():
            if key != 'default' and self.get_key(key):
                return int(self.config.speed_max * multiplier)
        return int(self.config.speed_max * self.controls.speed_controls['default'])

    def apply_countersteer(self, speed: int, direction: str) -> int:
        """Apply countersteer to help stop movement"""
        if speed > 0:
            if speed > self.config.speed_falloff:
                return max(-self.config.countersteer, 
                    speed - self.config.speed_falloff)
            return 0
        elif speed < 0:
            if speed < -self.config.speed_falloff:
                return min(self.config.countersteer, 
                    speed + self.config.speed_falloff)
            return 0
        return 0

    def update_controls(self, drone: tello.Tello) -> bool:
        """
        Update drone controls based on keyboard input.
        
        Returns:
            bool: True if any input was processed
        """
        try:
            # Update in_flight status from drone
            self.in_flight = drone.is_flying()
            any_input = False
            target_speed = self.get_target_speed()

            # Process movement controls
            for direction, keys in self.controls.movement_controls.items():
                if self.get_key(keys['pos']):
                    self.speeds[direction] = min(
                        self.speeds[direction] + self.config.speed_increase, 
                        target_speed
                    )
                    any_input = True
                elif self.get_key(keys['neg']):
                    self.speeds[direction] = max(
                        self.speeds[direction] - self.config.speed_increase, 
                        -target_speed
                    )
                    any_input = True
                else:
                    self.speeds[direction] = self.apply_countersteer(
                        self.speeds[direction], direction
                    )

            # Handle takeoff/landing
            current_time = time.time()
            cooldown_elapsed = (current_time - self.last_takeoff_time 
                              > self.config.takeoff_cooldown)

            if self.get_key("q") and self.in_flight and cooldown_elapsed:
                drone.land()
                self.in_flight = False
                any_input = True
                self.last_takeoff_time = current_time
            elif self.get_key("e") and not self.in_flight and cooldown_elapsed:
                drone.takeoff()
                self.in_flight = True
                any_input = True
                self.last_takeoff_time = current_time

            # Emergency stop
            if self.get_key("SPACE"):
                self.speeds = {k: 0 for k in self.speeds}
                any_input = True

            # Send control commands to drone
            drone.send_rc_control(
                self.speeds['lr'], 
                self.speeds['fb'], 
                self.speeds['ud'], 
                self.speeds['yv']
            )

            return any_input

        except Exception as e:
            self.logger.error(f"Error updating controls: {e}")
            return False


# Create global instance
drone_controller = DroneController()
initialize_drone = drone_controller.initialize_drone
update_controls = drone_controller.update_controls 