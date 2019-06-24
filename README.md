# go-e-controller
Simple controller to adjust car charging current to photovoltaic output with the Go-e-Charger

## assumptions
We have a 3 phase connection and a car that is able to load with 3 phases and 32A/22kW max.
The photovoltaic has less than 22 kW peak (in my case 13 kWp).
The loading should work with at least 6A/4.1kW (lower threshold of the go-e charger) and 20A/13.8kW (limit of the PV).
When the user is switching to 22 kW manually, this is respected and the current charging will do with 22 kW until the charge is over. After that, current is lowered to 16A.
Loading starts with 16A/11kW so that a charging effect is viable and is adjusted at the next run

