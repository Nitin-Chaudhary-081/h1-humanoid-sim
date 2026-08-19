from setuptools import find_packages, setup

package_name = 'h1_perception'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/aruco.yaml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='robot-agent',
    maintainer_email='robot-agent@example.com',
    description='M5: ArUco marker detection for H1 sim (pure logic + ROS node)',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'perception_node = h1_perception.perception_node:main',
        ],
    },
)