# Description
<p>This code is for a personal project of mine. It runs on a Raspberry Pi 5 that is mounted on a drone and communicates with the flight controller via MAVLink.</p>
<p>The objective is for a 14” quadcopter (Tarot 650 frame, 4214 motors, 6S battery, h743 flight controller + AM60 60A AM32 ESC) to go down from my third-floor balcony to a small box with mail, pick up the mail using an 80lb neodymium magnet mounted on the bottom of the frame, and fly back up to land on my balcony with my mail.</p>
<p>This code allows the Pi to control the drone autonomously. The Pi also logs the flight controller’s flight logs, but that code is on the Pi and not included in this repository.</p>
<img width="470" height="467" alt="Screenshot 2026-10-31 105249" src="https://github.com/user-attachments/assets/5d7fcf56-5744-45ce-9922-af013c6fe731" />
<img width="2090" height="925" alt="Screenshot 2026-10-31 104955" src="https://github.com/user-attachments/assets/5049cc01-91aa-42d9-8f91-00686cfad39a" />
<p>A GPS, LiDAR sensor, and Arducam camera are used for flight navigation:</p>
<ul>
  <li>The LiDAR sensor (which is connected to the flight controller and whose information is received by the Pi via MAVLink) initially detects that the drone is 2m above the balcony floor.</li>
  <li>The drone flies to the location where the box of mail is roughly located. It centers over the box using an AprilTag, which is detected by the Arducam mounted alongside the LiDAR sensor on the bottom of the frame.</li>
  <li>The drone then lands on top of the box (the magnet hangs below the feet of the landing gear and uses a spring to minimize the force applied to the frame. The spring also allows the drone to lower beyond where the magnet is hanging), flies up to its previous height, and flies back to the GPS coordinates of the balcony, where another AprilTag is used to guide the drone to where it will land on the balcony without the GPS error disrupting it.</li>
</ul>
<p>I can take over with the RC at any point, and most failures will automatically hand the RC control of the quadcopter.</p>
