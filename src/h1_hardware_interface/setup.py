from setuptools import find_packages, setup

package_name = 'h1_hardware_interface'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/bridge.yaml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='robot-agent',
    maintainer_email='robot-agent@example.com',
    description='ROS bridges between the H1-2 Unitree SDK and the h1 ROS graph',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'joint_state_bridge = h1_hardware_interface.joint_state_bridge:main',
            'command_bridge = h1_hardware_interface.command_bridge:main',
            'imu_bridge = h1_hardware_interface.imu_bridge:main',
            'lidar_bridge = h1_hardware_interface.lidar_bridge:main',
            'camera_bridge = h1_hardware_interface.camera_bridge:main',
        ],
    },
)