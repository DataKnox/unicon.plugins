'''
Author: Knox Hutchinson
Contact: https://dataknox.dev
https://twitter.com/data_knox
https://youtube.com/c/dataknox
Contents largely inspired by sample Unicon repo:
https://github.com/CiscoDevNet/pyats-plugin-examples/tree/master/unicon_plugin_example/src/unicon_plugin_example
'''

from unicon.plugins.dell import DellSingleRPConnection, DellServiceList
from .statemachine import Dellos6SingleRpStateMachine
from .settings import Dellos6Settings

class Dellos6ServiceList(DellServiceList):
    pass

class Dellos6SingleRPConnection(DellSingleRPConnection):
    '''DellosSingleRPConnection

    Dell OS6 platform support. Because our imaginary platform was inspired
    from Cisco IOSv platform, we are extending (inhering) from its plugin.
    '''    
    series = 'os6'
    state_machine_class = Dellos6SingleRpStateMachine
    subcommand_list = Dellos6ServiceList
    settings = Dellos6Settings()
