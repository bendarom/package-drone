This is a project for operating a drone.
All code will be run on a Raspberry Pi 5.
The drone will autonomously rise to a height of 1m above the ground on a balcony, fly toward a certain gps location, where an Apriltag is located, center the apriltag in the arducam pov, land on a box at that position (at which point the drone, which has a magnet on its bottom, will attach to the box), fly up, and fly toward the GPS location of the balcony, where there is another Apriltag that the camera will center onto so that the drone will land in position.
There is a lidar sensor soldered to the flight controller (skystars h7h3) on the drone, adn the arducam is connected to the pi.
The flight controller uses ardupilot firmware. It communicates with the Pi via mavlink.