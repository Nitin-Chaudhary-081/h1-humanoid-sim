from setuptools import find_packages, setup

package_name = 'h1_llm_agent'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/gemini.yaml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='robot-agent',
    maintainer_email='robot-agent@example.com',
    description='M3: Gemini natural-language agent with validation layer and estop for the H1 sim',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'agent_node = h1_llm_agent.agent_node:main',
        ],
    },
)
