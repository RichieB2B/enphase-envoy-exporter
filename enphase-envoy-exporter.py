#!/usr/bin/env python3
import sys
import time
import json
import prometheus_client as prom
import logging
import asyncio
import argparse

# local imports
from envoy_reader import EnvoyReader
import config

if __name__ == '__main__':
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
  while True:
    dataReceived = False
    # Update Envoy data endpoints
    asyncio.run(ER.getData())
    # Get general production data
    data = ER.endpoint_production_json_results.json()
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
    # Get inverter production data
    data = ER.endpoint_production_inverters.json()
    if data:
      dataReceived = True
      up.set(1)
      updated.set(time.time())
      for i in data:
        if i.keys() >= {'serialNumber','lastReportDate','lastReportWatts','maxReportWatts'}:
          array = config.arrays.get(i['serialNumber'], 'unknown')
          inverter_power.labels(i['serialNumber'], array, 'last').set(i['lastReportWatts'])
          inverter_power.labels(i['serialNumber'], array, 'max').set(i['maxReportWatts'])
          inverter_lastreport.labels(i['serialNumber'], array).set(i['lastReportDate'])
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
        inverter_temperature.labels(v[0], array).set(v[6])
        inverter_dc_voltage.labels(v[0], array).set(v[7]/1000.0)
        inverter_dc_current.labels(v[0], array).set(v[8]/1000.0)
        inverter_ac_voltage.labels(v[0], array).set(v[9]/1000.0)
        inverter_ac_power.labels(v[0], array).set(v[10])
    if not dataReceived:
      up.set(0)

    time.sleep(30)
