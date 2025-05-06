import datetime

import mlflow

run = mlflow.start_run()
ic(datetime.datetime.fromtimestamp(run.info.start_time / 1000, datetime.UTC))
ic(mlflow.get_tracking_uri())
ic(mlflow.active_run().info.run_name)
ic(mlflow.active_run().info.run_id)
ic(mlflow.active_run().info.experiment_id)
ic(mlflow.active_run().info.experiment_id)
mlflow.end_run()
