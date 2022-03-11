import argparse
import math

def convert_seconds_into_days(time_in_seconds):
    seconds_in_day = 86400.0
    seconds_in_hour = 3600.0
    seconds_in_minute = 60.0

    nb_days = math.floor(time_in_seconds/seconds_in_day)
    reste_days = time_in_seconds - (nb_days*seconds_in_day)

    nb_hours = math.floor(reste_days/seconds_in_hour)
    reste_hours = reste_days - (nb_hours*seconds_in_hour)

    nb_minutes = math.floor(reste_hours/seconds_in_minute)
    reste_minutes = reste_hours - (nb_minutes*seconds_in_minute)


    print("The conversion of " + str(time_in_seconds) + "s is : " + str(nb_days) + " days, " + str(nb_hours) + " hours, " + str(nb_minutes) + " minutes and " + str(reste_minutes) + " seconds.")

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--seconds", type=int, required=True)

    args = parser.parse_args()

    time_in_seconds = args.seconds

    convert_seconds_into_days(time_in_seconds)

