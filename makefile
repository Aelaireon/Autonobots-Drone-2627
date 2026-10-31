# Notes:
# create ros2 package: 
# ros2 pkg create <pkg_name> --build-type ament_cmake --dependencies rclcpp rclpy

############# Build ROS 2 Packages #############
all:
	colcon build --symlink-install
#	colcon build --symlink-install --packages-skip

#################### Setup ####################
open-serial:
# 	UART Pin Serial
	sudo chmod 777 /dev/ttyAMA0
clean:
	rm -rf build/ install/ log/

################## Pre-Flight ##################
mavros:
	ros2 launch uav_demo apm.launch
flow:
	python3 src/uav_demo/scripts/optical_flow.py
uav-node:
	python3 src/uav_demo/scripts/main.py
gcs:
	python3 ./src/uav_gcs_demo/scripts/uav_gcs.py
tfmini:
	ros2 run uav_demo tfmini.py

################## In-Flight ##################
gcs-deactivate-estop:
	ros2 topic pub --once /gcs_estop std_msgs/msg/Bool "{data: false}"
arm:
	ros2 service call /uav/mavros/cmd/arming mavros_msgs/srv/CommandBool "{value: true}"	
disarm:
	ros2 service call /uav/mavros/cmd/arming mavros_msgs/srv/CommandBool "{value: false}"
land:
	python3 src/uav_demo/scripts/land.force.disarm.py
kill:
	ros2 service call /uav/mavros/cmd/command mavros_msgs/srv/CommandLong "{command: 400, param2: 21196.0}"
reboot-fcu:
	ros2 service call /uav/mavros/cmd/command mavros_msgs/srv/CommandLong "{broadcast: false, command: 246, param1: 1.0,}"
status:
	ros2 topic echo /uav/mavros/state
takeoff:
	make guided
	make arm
	ros2 service call /uav/mavros/cmd/takeoff mavros_msgs/srv/CommandTOL "{altitude: 1.0}"
setpoint-1.1m:
	ros2 topic pub --rate 20 --times 100 /uav/mavros/setpoint_position/local geometry_msgs/msg/PoseStamped "{header: {frame_id: 'map'}, pose: {position: {x: 0.0, y: 0.0, z: 1.1}, orientation: {w: 1.0}}}"
setpoint-0.3m:
	ros2 topic pub --rate 20 --times 100 /uav/mavros/setpoint_position/local geometry_msgs/msg/PoseStamped "{header: {frame_id: 'map'}, pose: {position: {x: 0.0, y: 0.0, z: 0.3}, orientation: {w: 1.0}}}"
test-mavros:
	echo -e "\033[1;36m############### TAKING OFF TO 1 METER ...###############\033[0m"
	make takeoff | grep -E "success=|mode_sent=|GUIDED|arming"
	sleep 5
	echo -e "\033[1;36m################# GOING TO 1.1 METERS ...##################\033[0m"
	make setpoint-1.1m | grep "beginning"
	echo -e "\033[1;36m###################### LANDING ...#######################\033[0m"
	make land | grep "mode_sent="

#################### Debug ####################
viewframes:
	ros2 run tf2_tools view_frames
estop:
	ros2 topic pub --once /uav_estop std_msgs/msg/Bool "{data: true}" &
	ros2 topic pub --once /uav_estop std_msgs/msg/Bool "{data: true}" &
	ros2 topic pub --once /uav_estop std_msgs/msg/Bool "{data: true}"
estop-revert-state:
	ros2 topic pub --once /uav_estop std_msgs/msg/Bool "{data: false}"
keyboard-control:
	make estop-revert-state
	ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/uav_cmd_vel
	ros2 topic pub --once /uav_estop std_msgs/msg/Bool "{data: true}" &
	ros2 topic pub --once /uav_estop std_msgs/msg/Bool "{data: true}" &
	ros2 topic pub --once /uav_estop std_msgs/msg/Bool "{data: true}"