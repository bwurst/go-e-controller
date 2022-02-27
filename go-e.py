#!/usr/bin/python3
import sys
import os
import json
import re
import requests
import math
import logging
import subprocess
import traceback

configfile = os.path.join(os.path.dirname(sys.argv[0]), 'config.json')
if not os.path.exists(configfile):
    print('config.json not available!')
    sys.exit(1)
with open(configfile, 'r') as conf:
    config = json.load(conf)

# config-example: [{'goe-address': 'http://goe', 'pvtype': 'SBFspot', 'sbfspotconfig': 'Haus32.cfg'}]


logging.basicConfig(filename=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'go-e.log'),format='%(asctime)s %(levelname)s:%(message)s', level=logging.DEBUG)
#logging.basicConfig(filename=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'go-e.log'),format='%(asctime)s %(levelname)s:%(message)s', level=logging.INFO)

def get_sbfspot_current_wrapper(sbfspotconfig):
    def get_power():
        sbfspot = subprocess.run("~/bin/SBFspot/SBFspot -nocsv -v2 -cfg%s" % sbfspotconfig, shell=True, stdout=subprocess.PIPE, encoding='utf-8')
        try:
            for line in sbfspot.stdout.splitlines():
                if "Nothing to do... it's dark" in line:
                    return None
                if 'Total Pac' in line:
                    logging.debug('found Total Pac: ' + line)
                    m = re.search('(?P<power>[0-9.]+)kW', line)
                    power = int(m.group('power').replace('.', ''))
                    logging.debug('PV power: %.2f W' % power)
                    current = (power / 230) / 3
                    logging.debug('PV current: %.1f A' % current)
                    return power
        except:
            logging.error('error getting Pac from solar power plant')
            traceback.print_exc()

    return get_power


def get_shelly3em_current_wrapper(shellyhostname):
    def get_power():
        r = requests.get('http://%s/status' % (shellyhostname,))
        status = r.json()
        power = status['total_power']
        if power < 0:
            # pv gains!
            return -power
        return 0

    return get_power


class GOE(object):
    def __init__(self, address):
        self.status = {}
        self.address = address
        self.hostname = re.sub(r"https?://(?P<hostname>.*)/?$", r"\1", self.address)
        try:
            self.get_status()
        except RuntimeError:
            pass

    def __getitem__(self, var):
        try:
            return self.status[var]
        except:
            return None

    def __setitem__(self, var, val):
        try:
            self.set_var(var, val)
        except:
            pass

    def get_status(self):
        try:
            r = requests.get(self.address+'/api/status', timeout=20)
            self.status = r.json()
        except (requests.exceptions.ChunkedEncodingError, requests.exceptions.RequestException) as e:
            # connection problem
            logging.error('exception while getting status from charger "%s": %s' % (self.hostname, str(e)))
            raise RuntimeError('exception while getting status from charger "%s"' % self.hostname)
        #logging.debug(str(self.status))


    def set_var(self, var, value):
        oldval = self.status[var]
        logging.debug('%s: %s: old value: %s (type %s) / new value: %s (type: %s)' % (self.hostname, var, oldval, type(oldval), value, type(value)))
        if value == oldval:
            return
        logging.info('%s: set %s from %s to %s' % (self.hostname, var, oldval, value))
        payload='%s=%s' % (var, value)
        try:
            r = requests.get(self.address+'/api/set?'+payload, timeout=20)
            result = r.json()
            if not result[var]:
                logging.error('%s: api call returned '+r.text % self.hostname)
            self.get_status()
        except (requests.exceptions.ChunkedEncodingError, requests.exceptions.RequestException):
            logging.error('%s: exception while setting %s from %s to %s' % (self.hostname, var, oldval, value))
            pass
        if int(self.status[var]) != int(value):
            raise RuntimeError('charger "%s" did not accept value change' % self.hostname)

def work(goe_address, pvcallback, config):
    try:
        goe = GOE(goe_address)
        if not goe.status:
            raise RuntimeError('error initializing goe object')

        # when user selected 32A manually, don't touch. When 32A charging is over, current has been reset in the last step.
        if goe['amp'] == 32 and not (len(sys.argv) > 1 and sys.argv[1] == '-f'):
            # do not touch
            logging.info('%s: amp == 32, do not touch (use -f to override)' % (goe.hostname,))
            return

        # how many phases may be used?
        phases = 3
        if int(goe['psm']) == 1:
            phases = 1

        # how many phases uses the car?
        used_phases = 0
        for i in (4, 5, 6):
            if int(goe['nrg'][i]) > 0:
                used_phases += 1

        logging.info('%s: car = %s / amp = %s / phases=%s / used_phases=%s / alw=%s' % (goe.hostname, goe['car'], goe['amp'], phases, used_phases, goe['alw']));
        # car == 1: no car
        # car == 2: charge running
        # car == 3: waiting for car to get ready
        # car == 4: charge stopped, either full or paused by alw=false
        # when charge finished or no car is connected, reset to 16A on three phases for the next time
        if (int(goe['car']) == 1 or (int(goe['car']) == 4 and int(goe['alw']) == True)) and not (len(sys.argv) > 1 and sys.argv[1] == '-f'):
            if int(goe['amp']) != 16 or phases != 3:
                logging.info('%s: reset power to 16A' % goe.hostname)
                goe['amp'] = '16'
                goe['psm'] = '2'
            # do nothing else, as no car is connected
            logging.debug('%s: no car connected.' % (goe.hostname,))
            return

        logging.info('%s: car = %s / amp = %s / phases=%s / used_phases=%s / alw=%s' % (goe.hostname, goe['car'], goe['amp'], phases, used_phases, goe['alw']));

        # when car charges
        # look for PV current
        # calc max ampere from PV output
        power = 0
        try:
            # thows error sometimes, then leave all alone
            power = pvcallback()
            if not power:
                logging.info("%s: it's night" % goe.hostname)
                power = 0
            else:
                logging.info('%s: PV gains %s W' % (goe.hostname, power))
                # house usage: default ~500W
                consumption = 500
                if "consumption" in config:
                    consumption = config['consumption']
                power = max(power - consumption, 0)
                logging.info('%s: reducing PV by %s Watts, remaining charge power: %s W' % (goe.hostname, consumption, power))
        except Exception as e:
            logging.error('%s: error reading PV power: %s' % (goe.hostname, str(e)))
            # don't change
            return

        min_current = 10
        if "min_current" in config:
            min_current = config["min_current"]
        max_current = 30
        if "max_current" in config:
            max_current = config["max_current"]
        current = round((power / 230) / max(used_phases, 1))

        if phases == 1 and current < min_current:
            # bisher schon auf einer phase und dafür zu wenig leistung...
            logging.info('%s: power too low, stop charging.' % goe.hostname)
            goe['alw'] = False #stop
            return
        else:
            goe['alw'] = True #allow

        # Bleibt so lange auf einer Phase bis 30 Ampere (= Das Minimum von 10A auf 3 Phasen) überschritten werden
        # Bleibe so lange auf 3 Phasen, bis das Minimum unterschritten wird.
        if phases == 1 and current > max_current:
            # switch to three-phase-charging
            logging.info('%s: PV > %s A => switch to 3 phases' % (goe.hostname, max_current))
            goe['psm'] = 2
            phases = 3
        if current < min_current and phases == 3 and used_phases > 1:
            # switch to one-phase-charging
            logging.info('%s: PV < %s A => switch to 1 phase' % (goe.hostname, min_current))
            goe['psm'] = 1
            phases = 1

        current = round((power / 230) / max(1, min(used_phases, phases)))
        if current > max_current:
            current = max_current

        power = current * 230 * max(1, min(used_phases, phases))
        if current < min_current:
            logging.info('%s: PV power below minimum: %s A / %s W' % (goe.hostname, current, power))
            current = min_current
        power = current * 230 * max(1, min(used_phases, phases))
        logging.info('%s: setting charger to %s A / %s W (phases: %s / used_phases: %s)' % (goe.hostname, current, power, phases, min(used_phases, phases)))
        goe['amp'] = current

    except requests.exceptions.ConnectionError:
        logging.error('exception in main program')
        pass
    except RuntimeError:
        logging.error('exception in main program')
        pass

for system in config:
    get_current = None
    if system['pvtype'] == 'SBFspot':
        get_current = get_sbfspot_current_wrapper(system['sbfspotconfig'])
    elif system['pvtype'] == 'shelly3em':
        get_current = get_shelly3em_current_wrapper(system['shellyhostname'])
    work(system['goe_address'], get_current, system)

