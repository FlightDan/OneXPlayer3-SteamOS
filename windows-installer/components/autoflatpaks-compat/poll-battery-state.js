          this.intervalID = setInterval(() => {
              // OXP3 AutoFlatpaks compatibility: Steam may expose the store late.
              const currentState = window.SystemPowerStore?.batteryState;
              if (currentState == null || !Number.isFinite(currentState.eACState))
                  return;
              if (currentState != this.pseudoBatteryState)
                  this.setBatteryStateChange(currentState);
          }, 1000);
