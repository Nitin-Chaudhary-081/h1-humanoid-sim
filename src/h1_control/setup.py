from setuptools import find_packages, setup

package_name = 'h1_control'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/stand.yaml', 'config/joint_map.yaml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='robot-agent',
    maintainer_email='robot-agent@example.com',
    description='M2: stand + LocoMuJoCo walk replay controller for the H1-2 (Stand/Walk/Stop actions)',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'control_server = h1_control.control_server:main',
        ],
    },
)
