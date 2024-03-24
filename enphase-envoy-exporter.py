#!/usr/bin/env python3
import sys
import time
import json
from json.decoder import JSONDecodeError
import prometheus_client as prom
import logging
import asyncio
import argparse
import httpx

# local imports
from envoy_reader import EnvoyReader
import config

catchExceptions = (
  httpx.ReadTimeout,
  RuntimeError,
)

async def main():
  # Initialize EnvoyReader
  ER = EnvoyReader(
    host = config.host,
    https_flag = 's',
    enlighten_user = config.enlighten_user,
    enlighten_pass = config.enlighten_pass,
    enlighten_site_id = config.enlighten_site_id,
    enlighten_serial_num = config.enlighten_serial_num,
    commissioned=True,
    use_enlighten_owner_token=False,
    inverters=True,
  )
  cleared = time.time()
  while True:
    dataReceived = False
    # Update Envoy data endpoints
    try:
      await ER.getData()
    except catchExceptions as e:
      print(f'{type(e).__name__}: {str(e)}')
      sys.exit(1)
    # Get general production data
    try:
      data = ER.endpoint_production_json_results.json()
    except JSONDecodeError:
      data = {}
    prod = data.get('production',[])
    logging.debug(f'prod = {prod}')
    p = {}
    for i in prod:
      logging.debug(f'i = {i}')
      if i.get('type') == 'inverters':
        p = i
    if p:
      dataReceived = True
      up.set(1)
      updated.set(time.time())
      if p.keys() >= {'readingTime','wNow','whLifetime','activeCount'}:
        envoy_power.set(p['wNow'])
        envoy_production._value.set(p['whLifetime'])
        envoy_active.set(p['activeCount'])
        envoy_readingtime.set(p['readingTime'])
    # Once a day after midnight, clear all inverter metrics
    now = time.time()
    if now - cleared > 14400 and now % 86400 < 3600:
      logging.info('Clearing inverter metrics')
      cleared = now
      inverter_power.clear()
      inverter_ac_power.clear()
      inverter_ac_voltage.clear()
      inverter_dc_voltage.clear()
      inverter_dc_current.clear()
      inverter_temperature.clear()
      inverter_lastreport.clear()
    # Get inverter production data
    try:
      data = ER.endpoint_production_inverters.json()
    except JSONDecodeError:
      data = {}
    if data:
      dataReceived = True
      up.set(1)
      updated.set(now)
      for i in data:
        if i.keys() >= {'serialNumber','lastReportDate','lastReportWatts','maxReportWatts'}:
          array = config.arrays.get(i['serialNumber'], 'unknown')
          inverter_lastreport.labels(i['serialNumber'], array).set(i['lastReportDate'])
          if now - i['lastReportDate'] < 1800:
            inverter_power.labels(i['serialNumber'], array, 'last').set(i['lastReportWatts'])
            inverter_power.labels(i['serialNumber'], array, 'max').set(i['maxReportWatts'])
          else:
            # old data, remove metrics
            try:
              inverter_power.remove(i['serialNumber'], array, 'last')
            except KeyError:
              pass
            try:
              inverter_power.remove(i['serialNumber'], array, 'max')
            except KeyError:
              pass
    # Get inverter device status
    logging.debug(f'devstatus = {ER.endpoint_devstatus_json_results}')
    data = ER.endpoint_devstatus_json_results.json()
    if data:
      dataReceived = True
      up.set(1)
      updated.set(time.time())
      values = data.get('pcu',{}).get('values',[])
      for v in values:
        logging.debug(f'devstatus value = {v}')
        array = config.arrays.get(v[0], 'unknown')
        if v[1] == 1 and now - v[5] < 1800:
          logging.debug('Inverter devstatus is recent')
          inverter_temperature.labels(v[0], array).set(v[6])
          inverter_dc_voltage.labels(v[0], array).set(v[7]/1000.0)
          inverter_dc_current.labels(v[0], array).set(v[8]/1000.0)
          inverter_ac_voltage.labels(v[0], array).set(v[9]/1000.0)
          inverter_ac_power.labels(v[0], array).set(v[10])
        else:
          # old data, remove metrics
          try:
            inverter_temperature.remove(v[0], array)
          except KeyError:
            pass
          try:
            inverter_dc_voltage.remove(v[0], array)
          except KeyError:
            pass
          try:
            inverter_dc_current.remove(v[0], array)
          except KeyError:
            pass
          try:
            inverter_ac_voltage.remove(v[0], array)
          except KeyError:
            pass
          try:
            inverter_ac_power.remove(v[0], array)
          except KeyError:
            pass
    if not dataReceived:
      up.set(0)

    time.sleep(30)

if __name__ == '__main__':
  sys.stdout.reconfigure(line_buffering=True)
  sys.stderr.reconfigure(line_buffering=True)
  parser = argparse.ArgumentParser('Enphase Envoy Exporter')
  parser.add_argument('-d', '--debug', action='store_true')
  parser.add_argument('-p', '--port', type=int, default=8085)
  args = parser.parse_args()
  if args.debug:
    level=logging.DEBUG
  else:
    level=logging.INFO
  logging.basicConfig(level=level)

  envoy_power         = prom.Gauge('envoy_power'              , 'Power in Watt', unit='watts')
  envoy_production    = prom.Counter('envoy_production'       , 'Production in Wh', unit='whs')
  envoy_active        = prom.Gauge('envoy_active'             , 'Number of active inverters', unit='count')
  envoy_readingtime   = prom.Gauge('envoy_readingtime'        , 'Time of reading')
  inverter_power      = prom.Gauge('envoy_inverter_power'     , 'Power in Watt', ['serialnumber', 'array', 'type'], unit='watts')
  inverter_ac_power   = prom.Gauge('envoy_inverter_ac_power'  , 'Power in Watt', ['serialnumber', 'array'], unit='watts')
  inverter_ac_voltage = prom.Gauge('envoy_inverter_ac_voltage', 'Voltage in Volt', ['serialnumber', 'array'], unit='volt')
  inverter_dc_voltage = prom.Gauge('envoy_inverter_dc_voltage', 'Voltage in Volt', ['serialnumber', 'array'], unit='volt')
  inverter_dc_current = prom.Gauge('envoy_inverter_dc_current', 'Current in Ampere', ['serialnumber', 'array'], unit='ampere')
  inverter_temperature= prom.Gauge('envoy_inverter_temperature','Temperature in Celsius', ['serialnumber', 'array'], unit='celsius')
  inverter_lastreport = prom.Gauge('envoy_inverter_lastreport', 'Time in epoch', ['serialnumber', 'array'])
  updated             = prom.Gauge('envoy_updated'            , 'Envoy client last updated')
  up                  = prom.Gauge('envoy_up'                 , 'Envoy client status')
  prom.start_http_server(args.port)

  asyncio.run(main())
