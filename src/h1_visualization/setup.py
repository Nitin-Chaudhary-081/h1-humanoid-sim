from setuptools import find_packages, setup

package_name = 'h1_visualization'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/foxglove_layout.json']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='robot-agent',
    maintainer_email='robot-agent@example.com',
    description='M2/M3: Foxglove layout + markers for control state and goals',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'viz_node = h1_visualization.viz_node:main',
        ],
    },
)
