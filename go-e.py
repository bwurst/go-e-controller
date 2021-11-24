#!/usr/bin/python3

GOE_ADDRESS="http://goe"

import re
import requests
import math
import logging
import os.path
import subprocess
import traceback
import sys

#logging.basicConfig(filename=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'go-e.log'),format='%(asctime)s %(levelname)s:%(message)s', level=logging.DEBUG)
logging.basicConfig(filename=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'go-e.log'),format='%(asctime)s %(levelname)s:%(message)s', level=logging.INFO)


def get_pv_current():
    sbfspot = subprocess.run("~/bin/SBFspot/SBFspot -nocsv -v2 -cfgHaus32.cfg", shell=True, stdout=subprocess.PIPE, encoding='utf-8')
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


class GOE(object):
    status = {}

    def __init__(self):
        self.get_status()

    def __getitem__(self, var):
        return self.status[var]

    def __setitem__(self, var, val):
        self.set_var(var, val)

    def get_status(self):
        r = requests.get(GOE_ADDRESS+'/api/status')
        self.status = r.json()
        logging.debug(str(self.status))


    def set_var(self, var, value):
        oldval = self.status[var]
        logging.debug('old value: %s (type %s) / new value: %s (type: %s)' % (oldval, type(oldval), value, type(value)))
        if value == oldval:
            return
        logging.info('set %s from %s to %s' % (var, oldval, value))
        payload='%s=%s' % (var, value)
        r = requests.get(GOE_ADDRESS+'/api/set?'+payload)
        if r.text != '1 succeeded and 0 failed.':
            logging.error('api call returned '+r.text)
        self.get_status()
        if int(self.status[var]) != int(value):
            raise RuntimeError('charger did not accept value change')

try:
    goe = GOE()

    phases = 3
    if int(goe['psm']) == 1:
        phases = 1
    if int(goe['amp']) != 16 or phases != 3:
        logging.info('car = %s / amp = %s / phases=%s' % (goe['car'], goe['amp'], phases));

    # when charge is done and car still connected, always reset to 16A for the next time
    # if goe['car'] == 4: set amp=16
    if int(goe['car']) == 4 and (int(goe['amp']) != 16 or phases != 3):
        logging.info('reset power to 16A')
        goe['amp'] = '16'
        goe['psm'] = '2'

    # when user selected 32A manually, don't touch. When 32A charging is over, current has been reset in the last step.
    # if goe['amp'] == 32: do nothing
    # our work is to be done when car is charging!
    # if goe['car'] == 2: run
    if int(goe['amp']) != 32 and (int(goe['car']) == 2 or (len(sys.argv) > 1 and sys.argv[1] == '-f')):
        # when car charges
        # look for PV current
        # calc max ampere from PV output
        try:
            # thows error sometimes, then leave all alone
            pv = get_pv_current()
            if not pv:
                # it's night switch to 11kW charge, it does not matter
                logging.info("it's night, switch to 16A on three phases to get the car full")
                pv=11540
            logging.info('PV gains %s W' % pv)
            # house usage: ~500W
            pv = max(pv - 500, 0)
            pv_current = round((pv / 230) / 3)
            logging.info('reducing PV by 500 Watts, remaining charge power: %s W / %s A' % (pv, pv_current))
        except:
            logging.error('error reading PV power')
            # don't change
            pv = int(goe['amp']) * 230 * 3
            pv_current = int(goe['amp'])

        # if pv['amp'] < 6: goe['amp'] = 6
        # else: goe['amp'] = pv['amp']
        if phases == 1 and pv_current > 10:
            # switch to three-phase-charging
            logging.info('PV > 10 => switch to 3 phases')
            goe['psm'] = 2
            phases = 3
        if pv_current < 10 and phases == 3:
            # switch to one-phase-charging
            logging.info('PV < 10 => switch to 1 phase')
            goe['psm'] = 1
            phases = 1
        if phases == 1:
            pv_current = round(pv / 230)
        logging.info('loading on %i phase(s) with %s A, using %i W' % (phases, pv_current, pv_current * phases * 230))
        if pv_current < 10:
            logging.info('PV == %s (< 10) => 10' % (pv_current,))
            goe['amp'] = 10
        else:
            logging.info('PV = %s => %s' % (pv_current, pv_current))
            goe['amp'] = pv_current
except requests.exceptions.ConnectionError:
    logging.error('exception in main program')
    pass

