import argparse
import configparser
import json
import os
import re
import sys
from base64 import b64encode
from datetime import datetime
from xml.sax.saxutils import escape as escape_xml

import requests


def write_configfile(config, filename):
    """Create sufferfest.cfg file in current directory."""
    text = r"""
[DEFAULT]
# Change these to 1 if you want to upload the respective workouts to intervals.icu
UPLOAD_RUN_WORKOUTS = 0
UPLOAD_SWIM_WORKOUTS = 0
UPLOAD_STRENGTH_WORKOUTS = 0
UPLOAD_YOGA_WORKOUTS = 0
# Change this to 1 if you want to upload past SYSTM workouts to intervals.icu
UPLOAD_PAST_WORKOUTS = 0
UPLOAD_DESCRIPTION = 0

[WAHOO]
# Your Wahoo SYSTM credentials
SYSTM_USERNAME = your_systm_username
SYSTM_PASSWORD = your_systm_password

# Start and end date of workouts you want to send to intervals.icu.
# Use YYYY-MM-DD format
START_DATE = 2022-01-01
END_DATE = 2022-12-31

[INTERVALS.ICU]
# Your intervals.icu API ID and API key
INTERVALS_ICU_ID = i00000
INTERVALS_ICU_APIKEY = xxxxxxxxxxxxx
"""
    with open(filename, 'w') as configfile:
        configfile.write(text)
    print(f'Created {filename}. Add your user details to that file and run suffersync again.')
    sys.exit(0)


def get_systm_token(url, username, password):
    """Returns Wahoo SYSTM API token."""
    payload = json.dumps({
        "operationName": "Login",
        "variables": {
            "appInformation": {
                "platform": "web",
                "version": "7.12.0-web.2141",
                "installId": "F215B34567B35AC815329A53A2B696E5"
            },
            "username": username,
            "password": password
        },
        "query": "mutation Login($appInformation: AppInformation!, $username: String!, $password: String!) { loginUser(appInformation: $appInformation, username: $username, password: $password) { status message user { ...User_fragment __typename } token failureId __typename }}fragment User_fragment on User { id fullName firstName lastName email gender birthday weightKg heightCm createdAt metric emailSharingOn legacyThresholdPower wahooId wheelSize { name id __typename } updatedAt profiles { riderProfile { ...UserProfile_fragment __typename } __typename } connectedServices { name __typename } timeZone onboardingProgress { complete completedSteps __typename } subscription { validUntil trialAvailable __typename } avatar { url original { url __typename } square200x200 { url __typename } square256x256 { url __typename } thumb { url __typename } __typename } onboardingComplete createdWithAppInformation { version platform __typename } __typename}fragment UserProfile_fragment on UserProfile { nm ac map ftp lthr cadenceThreshold riderTypeInfo { name icon iconSmall systmIcon description __typename } riderWeaknessInfo { name __typename } recommended { nm { value activity __typename } ac { value activity __typename } map { value activity __typename } ftp { value activity __typename } __typename } __typename}"
    })

    headers = {'Content-Type': 'application/json'}

    response = call_api(url, "POST", headers, payload)
    if 'login.badUserOrPassword' in response.text:
        print('Invalid Wahoo SYSTM username or password. Please check your settings and try again.')
        sys.exit(1)
    response_json = response.json()
    token = response_json['data']['loginUser']['token']
    rider_profile = response_json['data']['loginUser']['user']['profiles']['riderProfile']
    get_systm_profile(rider_profile)
    return token

def get_intervals_sport(sport):
    """Translate Wahoo SYSTM sport type into intervals.icu type."""
    if sport == "Cycling":
        return "Ride"
    elif sport == "Running":
        return "Run"
    elif sport == "Yoga":
        return "Yoga"
    elif sport == "Strength":
        return "WeightTraining"
    elif sport == "Swimming":
        return "Swim"
    else:
        return sport


def get_systm_profile(profile):
    """Get Wahoo SYSTM 4DP profile and set as global variables."""
    global rider_ac, rider_nm, rider_map, rider_ftp
    rider_ac = profile['ac']
    rider_nm = profile['nm']
    rider_map = profile['map']
    rider_ftp = profile['ftp']


def get_systm_workouts(url, token, start_date, end_date):
    """Get Wahoo SYSTM workouts for specified date range and return response."""
    payload = json.dumps({
        "operationName": "GetUserPlansRange",
        "variables": {
            "startDate": f"{start_date}T00:00:00.000Z",
            "endDate": f"{end_date}T23:59:59.999Z",
            "queryParams": {
                "limit": 1000
            }
        },
        "query": "query GetUserPlansRange($startDate: Date, $endDate: Date, $queryParams: QueryParams) { userPlan(startDate: $startDate, endDate: $endDate, queryParams: $queryParams) { ...UserPlanItem_fragment __typename }}fragment UserPlanItem_fragment on UserPlanItem { day plannedDate rank agendaId status type appliedTimeZone completionData { name date activityId durationSeconds style deleted __typename } prospects { type name compatibility description style intensity { master nm ac map ftp __typename } trainerSetting { mode level __typename } plannedDuration durationType metrics { ratings { nm ac map ftp __typename } __typename } contentId workoutId notes fourDPWorkoutGraph { time value type __typename } __typename } plan { id name color deleted durationDays startDate endDate addons level subcategory weakness description category grouping option uniqueToPlan type progression planDescription volume __typename } __typename}"
    })

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    # Get workouts from Wahoo SYSTM plan
    response = call_api(url, "POST", headers, payload).json()

    # Even with errors, response.status_code comes back as 200 so catching errors this way.
    if 'errors' in response:
        print(f'Wahoo SYSTM Error: {response["errors"][0]["message"]}')
        sys.exit(1)
    return response


def get_systm_workout(url, token, workout_id):
    """Get Wahoo SYSTM details for specific workout and return response."""
    payload = json.dumps({
        "operationName": "GetWorkouts",
        "variables": {
            "id": workout_id
        },
        "query": "query GetWorkouts($id: ID) {workouts(id: $id) { id sortOrder sport stampImage bannerImage bestFor equipment { name description thumbnail __typename } details shortDescription level durationSeconds name triggers featuredRaces { name thumbnail darkBackgroundThumbnail __typename } metrics { intensityFactor tss ratings { nm ac map ftp __typename } __typename } brand nonAppWorkout notes tags imperatives { userSettings { birthday gender weight __typename } __typename } __typename}}"
    })

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    response = call_api(url, "POST", headers, payload).text
    return response

def get_systm_workout_json(url, token, workout_id):
    """Get Wahoo SYSTM details for specific workout and return response."""
    payload = json.dumps({
        "operationName": "GetWorkouts",
        "variables": {
            "id": workout_id
        },
        "query": "query GetWorkouts($id: ID) {workouts(id: $id) { id sortOrder sport stampImage bannerImage bestFor equipment { name description thumbnail __typename } details shortDescription level durationSeconds name triggers featuredRaces { name thumbnail darkBackgroundThumbnail __typename } metrics { intensityFactor tss ratings { nm ac map ftp __typename } __typename } brand nonAppWorkout notes tags imperatives { userSettings { birthday gender weight __typename } __typename } __typename}}"
    })

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    response = call_api(url, "POST", headers, payload).json()
    return response


def get_library(url, token):
    payload = json.dumps({
        "operationName": "library",
        "variables": {
            "appInformation": {
                "platform": "web",
                "version": "7.12.0-web.2141",
                "installId": "F215B34567B35AC815329A53A2B696E5"
            },
            "locale": "en"
        },
        "query": """query library($locale: Locale!, $queryParams: QueryParams, $appInformation: AppInformation!) {
  library(locale: $locale, queryParams: $queryParams, appInformation: $appInformation) {
    config {
      ...LibraryConfigFragment
      __typename
    }
    channels {
      id
      name
      description
      priority
      icon
      bannerImage
      publishInfo {
        publishDate
        expirationDate
        __typename
      }
      __typename
    }
    content {
      id
      name
      mediaType
      channel
      workoutType
      category
      level
      order
      duration
      lists {
        title
        viewLimit
        items {
          type
          value
          link {
            name
            url
            action
            __typename
          }
          __typename
        }
        __typename
      }
      equipment {
        id
        name
        description
        thumbnail
        icon
        link {
          name
          url
          action
          __typename
        }
        __typename
      }
      featured {
        title
        featuring {
          icon
          altText
          __typename
        }
        __typename
      }
      metrics {
        ratings {
          ac
          nm
          map
          ftp
          __typename
        }
        tss
        intensityFactor
        if
        __typename
      }
      workoutId
      videoId
      descriptions {
        title
        body
        alerts {
          icon
          message
          severity
          __typename
        }
        __typename
      }
      publishInfo {
        publishDate
        expirationDate
        __typename
      }
      bannerImage
      posterImage
      defaultImage
      intervalDuration
      intensity
      roles
      tags
      featured {
        title
        featuring {
          icon
          altText
          __typename
        }
        __typename
      }
      fitnessTest
      subscriberTypes
      __typename
    }
    sports {
      id
      workoutType
      name
      description
      defaultImage
      bannerImage
      __typename
    }
    __typename
  }
}

fragment LibraryConfigFragment on LibraryConfig {
  configID
  global {
    content {
      filterConfig {
        ...GlobalFilterConfig
        __typename
      }
      sortConfig {
        ...SortConfigFragment
        __typename
      }
      __typename
    }
    channel {
      filterConfig {
        ...GlobalFilterConfig
        __typename
      }
      sortConfig {
        ...SortConfigFragment
        __typename
      }
      __typename
    }
    __typename
  }
  content {
    workoutType
    filterConfig {
      ...ContentFilterConfig
      __typename
    }
    sortConfig {
      allowGlobals
      default
      ...SortConfigFragment
      __typename
    }
    __typename
  }
  __typename
}

fragment GlobalFilterConfig on LibraryFilterConfig {
  filters {
    ...FiltersFragment
    __typename
  }
  __typename
}

fragment FiltersFragment on LibraryFilterGroup {
  key
  type
  displayName
  allowAllText
  hideOnPlatforms
  dynamicallyGenerate {
    field
    __typename
  }
  options {
    key
    displayName
    rules {
      operation
      parameter
      field
      __typename
    }
    __typename
  }
  __typename
}

fragment SortConfigFragment on LibrarySortConfig {
  options {
    key
    displayName
    field
    hideOnPlatforms
    __typename
  }
  __typename
}

fragment ContentFilterConfig on LibraryFilterConfig {
  allowGlobals
  filters {
    ...FiltersFragment
    __typename
  }
  __typename
}
"""})
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    response = call_api(url, "POST", headers, payload).json()
    return response


def get_preview_plan_list(url, token):
    payload = json.dumps({
        "operationName": "GetPreviewPlanList",
        "variables": {
            "profile": {
                "nm": 0,
                "ac": 0,
                "map": 0,
                "ftp": 0,
                "riderWeakness": "Sustained",
#                "riderType": null
            },
            "queryParams": {
                "limit": 2000
            },
            "appInfo": {
                "platform": "web",
                "version": "7.20.0-web.2456"
            }
        },
        "query": "query GetPreviewPlanList($profile: Profile, $queryParams: QueryParams, $appInfo: AppInformation) {  previewPlan(profile: $profile, queryParams: $queryParams, appInformation: $appInfo) {    id    name    planDescription    weakness    grouping    category    subcategory    addOnIds    level    type    uniqueToPlan    fixedEndDate    volume    option    duration    progression    hidden    __typename  }}"
    })

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    response = call_api(url, "POST", headers, payload).json()
    return response


def call_api(url, method, headers, payload=None):
    """Call REST API and return response."""
    try:
        response = requests.request(method, url, headers=headers, data=payload)
        response.raise_for_status()
    except Exception as err:
        raise(err)
    return response


def clean_workout(workout):
    """Return workout with interval details as JSON string."""
    workout_json = json.loads(workout)
    workout_json['data']['workouts'][0]['triggers'] = json.loads(workout_json['data']['workouts'][0]['triggers'])
    return workout_json

def create_file(UPLOAD_DESCRIPTION, url_id, workout_type, workout_name, workout_detail):
    workout_name_remove_colon = re.sub("[:]", "", workout_name)
    workout_name_underscores = re.sub("[ ,./]", "_", workout_name_remove_colon)
    filename = f'{workout_name_underscores}'

        # get_intervals_sport will get the intervals.icu name for SYSTM's equivalent sport
    sport = get_intervals_sport(workout_type)
    if sport == '':
      print("no sport found")


        # Create .zwo files with workout details
    filename_zwo = f'./zwo/{sport}/{filename}.zwo'
    os.makedirs(os.path.dirname(filename_zwo), exist_ok=True)

    try:
            # Workout details contain nested JSON, so use clean_workout() to handle this.
        workout_json = clean_workout(workout_detail)

        sporttype = ''
        if sport == 'Ride':
            sporttype = 'bike'

            # If UPLOAD_DESCRIPTION is set, change description of workout to Wahoo SYSTM's description.
        description = ''
        short_description =  ''
        notes = ''
        source = f'https://systm.wahoofitness.com/content-details/{url_id}'

            # Escape XML from description
        if UPLOAD_DESCRIPTION and workout_json['data']['workouts'][0]['details']:
            description = workout_json['data']['workouts'][0]['details']
            description = escape_xml(description)

        if UPLOAD_DESCRIPTION and workout_json['data']['workouts'][0]['shortDescription']:
            short_description =  workout_json['data']['workouts'][0]['shortDescription']
            short_description = escape_xml(short_description)

        if UPLOAD_DESCRIPTION and workout_json['data']['workouts'][0]['notes']:
            notes =  workout_json['data']['workouts'][0]['notes']
            notes = escape_xml(notes)

        total_description = notes + short_description + description + source

            # 'triggers' contains the FTP values for the workout
        workout_json = workout_json['data']['workouts'][0]['triggers']

        f = open(filename_zwo, "w")
        text = f"""
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workout_file>
<author></author>
<name>{workout_name}</name>
<description>{total_description}</description>
<sportType>{sporttype}</sportType>
<tags/>
<workout>"""
        f.write(text)

        for interval in range(len(workout_json)):
            for tracks in range(len(workout_json[interval]['tracks'])):
                for item in workout_json[interval]['tracks'][tracks]['objects']:
                    power = None
                    seconds = int(item['size'] / 1000)
                    if 'ftp' in item['parameters']:
                        power = item['parameters']['ftp']['value']
                        # Not sure if required, in my data this always seems to be the same as ftp
                    if 'twentyMin' in item['parameters']:
                        twentyMin = item['parameters']['twentyMin']['value']
                        power = twentyMin
                        absolute_power = round(power * rider_ftp)
                        # If map value exists, set ftp to the higher value of either map or ftp.
                    if 'map' in item['parameters']:
                        map = item['parameters']['map']['value'] * round(rider_map / rider_ftp, 2)
                        power = map
                        absolute_power = round(power * rider_ftp)
                    if 'ac' in item['parameters']:
                        ac = item['parameters']['ac']['value'] * round(rider_ac / rider_ftp, 2)
                        power = ac
                        absolute_power = round(power * rider_ftp)
                    if 'nm' in item['parameters']:
                        nm = item['parameters']['nm']['value'] * round(rider_nm / rider_ftp, 2)
                        power = nm
                        absolute_power = round(power * rider_ftp)
                    if power:
                        if 'rpm' in item['parameters']:
                            rpm = item['parameters']['rpm']['value']
                            text = f'\n\t\t<SteadyState show_avg="1" Cadence="{rpm}" Power="{power}" Duration="{seconds}"/><!-- abs power: {absolute_power} -->'
                        else:
                            text = f'\n\t\t<SteadyState show_avg="1" Power="{power}" Duration="{seconds}"/><!-- abs power: {absolute_power} -->'
                        f.write(text)
        text = r"""
</workout>
</workout_file>"""
        f.write(text)

    except Exception as err:
        print(f'{err}')

    f.close()

def main():
    """Main function"""
    # Read config file, create it if it doesn't exist
    CONFIGFILE = 'suffersync.cfg'
    SYSTM_URL = "https://api.thesufferfest.com/graphql"

    config = configparser.ConfigParser(interpolation=None)

    config_exists = os.path.exists(CONFIGFILE)
    if config_exists:
        try:
            config.read(CONFIGFILE)
            UPLOAD_PAST_WORKOUTS = config.getint('DEFAULT', 'UPLOAD_PAST_WORKOUTS', fallback=0)
            UPLOAD_STRENGTH_WORKOUTS = config.getint('DEFAULT', 'UPLOAD_STRENGTH_WORKOUTS', fallback=0)
            UPLOAD_YOGA_WORKOUTS = config.getint('DEFAULT', 'UPLOAD_YOGA_WORKOUTS', fallback=0)
            UPLOAD_RUN_WORKOUTS = config.getint('DEFAULT', 'UPLOAD_RUN_WORKOUTS', fallback=0)
            UPLOAD_SWIM_WORKOUTS = config.getint('DEFAULT', 'UPLOAD_SWIM_WORKOUTS', fallback=0)
            UPLOAD_DESCRIPTION = config.getint('DEFAULT', 'UPLOAD_DESCRIPTION', fallback=0)
            SYSTM_USERNAME = config.get('WAHOO', 'SYSTM_USERNAME')
            SYSTM_PASSWORD = config.get('WAHOO', 'SYSTM_PASSWORD')
            START_DATE = config.get('WAHOO', 'START_DATE')
            END_DATE = config.get('WAHOO', 'END_DATE')
            INTERVALS_ICU_ID = config.get('INTERVALS.ICU', 'INTERVALS_ICU_ID')
            INTERVALS_ICU_APIKEY = config.get('INTERVALS.ICU', 'INTERVALS_ICU_APIKEY')
        except KeyError as err:
            print(f'No valid value found for key {err} in {CONFIGFILE}.')
            sys.exit(1)
    else:
        write_configfile(config, CONFIGFILE)

    # Check CLI arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--delete', help='Delete all events for the specified date range in intervals.icu.', action='store_true')
    args = parser.parse_args()

    # Get Wahoo SYSTM auth token
    systm_token = get_systm_token(SYSTM_URL, SYSTM_USERNAME, SYSTM_PASSWORD)

    # Get Wahoo SYSTM workouts from training plan
    workouts = get_systm_workouts(SYSTM_URL, systm_token, START_DATE, END_DATE)

    # Only get the workout portion of the returned data
    workouts = workouts['data']['userPlan']

    plan_list = get_preview_plan_list(SYSTM_URL, systm_token)
    #plan_list = plan_list['data']

    library = get_library(SYSTM_URL, systm_token)
    library = library['data']['library']

    #print(json.dumps(library, indent=4, sort_keys=True))
    #exit(0)

    content_list = library['content']
    for item in content_list:
        name = item['name']
        url_id = item['id']

        if url_id == 'PK6PPpoW3Q':
           print(f'url_id = {url_id}')
        else:
           continue

        workout_id = item['workoutId']

        if workout_id == '':
          print(f'no details found for {name}')

        workout_type = item['workoutType']

        if (workout_type == 'MountainBiking'):
          descriptions = item['descriptions']
          a = descriptions[0]['body']

        tss = item['metrics']['tss']

        workout_detail_json = get_systm_workout_json(SYSTM_URL, systm_token, workout_id)
        workout = workout_detail_json['data']['workouts'][0];
        workout_name = workout['name']

        print(f' url_id: {url_id} workout_id: {workout_id}: "{name}" "{workout_name}" ({workout_type}) TSS: {tss}')

        # Get specific workout
        workout_detail = get_systm_workout(SYSTM_URL, systm_token, workout_id)

        create_file(UPLOAD_DESCRIPTION, url_id, workout_type, workout_name, workout_detail)


if __name__ == "__main__":
    main()
