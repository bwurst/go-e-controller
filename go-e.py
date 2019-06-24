#!/usr/bin/python3

GOE_ADDRESS="http://goe/"

import requests
import math
import logging
import os.path

logging.basicConfig(filename=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'go-e.log'),format='%(asctime)s %(levelname)s:%(message)s', level=logging.DEBUG)


def get_pv_current():
    # HACKY
    # we don't have a connection to the right PV installation yet, so we do fetch percentage of our other installation (similar orientation) and calculate this down.
    # good one: this script runs on the server that holds the FTP data exported by solarlog. So we can use the local file system here.
    pac = 0
    with open('/home/ftp/data/solarlog/min_cur.js', 'r') as data:
        for line in data.readlines():
            if line.startswith('var Pac='):
                pac = int(line[8:])
    assert pac > 0
    logging.debug('PV pac: %s' % pac)
    # other installation has 40230 Wp
    percent = pac/40230
    logging.debug('PV result: %.2f %%' % (percent*100))
    # our installation has 15300 Wp
    power = percent*15300
    logging.debug('PV power: %.2f W' % power)
    current = (power / 230) / 3
    logging.debug('PV current: %.1f A' % current)
    return math.floor(current)



class GOE(object):
    status = {}

    def __init__(self):
        self.get_status()

    def __getitem__(self, var):
        logging.debug('goe['+var+'] = '+self.status[var])
        return self.status[var]

    def __setitem__(self, var, val):
        self.set_var(var, val)

    def get_status(self):
        r = requests.get(GOE_ADDRESS+'status')
        self.status = r.json()


    def set_var(self, var, value):
        oldval = self.status[var]
        if value == oldval:
            return
        logging.info('set %s from %s to %s' % (var, oldval, value))
        payload='%s=%s' % (var, value)
        r = requests.get(GOE_ADDRESS+'mqtt?payload='+payload)
        self.status = r.json()
        if self.status[var] != value:
            raise RuntimeError('charger did not accept value change')

try:
    goe = GOE()


    # when charge is done and car still connected, always reset to 16A for the next time
    # if goe['car'] == 4: set amp=16
    if goe['car'] == 4 and goe['amp'] != 16:
        goe['amp'] = 16


    # when user selected 32A manually, don't touch. When 32A charging is over, current has been reset in the last step.
    # if goe['amp'] == 32: do nothing
    # our work is to be done when car is charging!
    # if goe['car'] == 2: run
    if goe['amp'] != 32 and goe['car'] == 2:
        # when car charges
        # look for PV current
        # calc max ampere from PV output
        try:
            # thows error sometimes, then leave all alone
            pv = get_pv_current()
        except:
            # don't change
            pv = goe['amp']

        # if pv['amp'] < 6: goe['amp'] = 6
        # elif pv['amp'] > 20: goe['amp'] = 20
        # else: goe['amp'] = pv['amp']
        if pv < 6:
            logging.debug('PV < 6 => 6')
            goe['amp'] = '6'
        elif pv > 20:
            logging.debug('PV > 20 => 20')
            goe['amp'] = '20'
        else:
            logging.debug('PV = %s => %s' % (pv, pv))
            goe['amp'] = '%s' % pv
except requests.exceptions.ConnectionError:
    pass

