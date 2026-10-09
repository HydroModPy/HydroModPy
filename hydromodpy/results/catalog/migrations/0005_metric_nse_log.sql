-- =====================================================================
-- One name for the NSE on log-transformed series: nse_log
-- =====================================================================
--
-- A calibration scores `metric = "nse_log"`, and the fit panel a run
-- writes next to its observations stored the same quantity as
-- `log_nse`. `@best:nse_log` therefore found no run, and `@best:log_nse`
-- ranked a metric no calibration file can name. The run panel now
-- writes `nse_log`; this renames the rows written before.
--
-- A row already stored under the new name wins over its old twin.

DELETE FROM metrics AS old
WHERE old.metric_name = 'log_nse'
  AND EXISTS (
      SELECT 1 FROM metrics AS new
      WHERE new.sim_id = old.sim_id
        AND new.station_id = old.station_id
        AND new.variable = old.variable
        AND new.metric_name = 'nse_log'
  );

UPDATE metrics SET metric_name = 'nse_log' WHERE metric_name = 'log_nse';
