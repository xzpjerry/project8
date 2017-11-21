import flask
from flask import render_template
from flask import request
from flask import url_for
import uuid

import json
import logging

# Date handling
import arrow  # Replacement for datetime, based on moment.js
# import datetime # But we still need time
from dateutil import tz  # For interpreting local times


# OAuth2  - Google library implementation for convenience
from oauth2client import client
import httplib2   # used in oauth2 flow

# Google API for services
from apiclient import discovery

import model
from math import ceil
###
# Globals
###
import config
if __name__ == "__main__":
  CONFIG = config.configuration()
else:
  CONFIG = config.configuration(proxied=True)

app = flask.Flask(__name__)
app.debug = CONFIG.DEBUG
app.logger.setLevel(logging.DEBUG)
app.secret_key = CONFIG.SECRET_KEY

SCOPES = 'https://www.googleapis.com/auth/calendar.readonly'
CLIENT_SECRET_FILE = CONFIG.GOOGLE_KEY_FILE  # You'll need this
APPLICATION_NAME = 'MeetMe class project'

Calendars_checked = {}
Cal_id_2_summary = {}
Set_range = None

#############################
#
#  Pages (routed from URLs)
#
#############################


@app.route("/")
@app.route("/index")
def index():
  app.logger.debug("Entering index")
  if 'begin_date' not in flask.session:
    init_session_values()
  return render_template('index.html')


@app.route("/choose")
def choose():
    # We'll need authorization to list calendars
    # I wanted to put what follows into a function, but had
    # to pull it back here because the redirect has to be a
    # 'return'
  def worker_on(gcal_service):
    flask.g.calendars = list_calendars(gcal_service)
    flask.g.busy_list = get_busy(gcal_service, flask.g.calendars)

  app.logger.debug("Checking credentials for Google calendar access")
  credentials = valid_credentials()
  if not credentials:
    app.logger.debug("Redirecting to authorization")
    return flask.redirect(flask.url_for('oauth2callback'))

  gcal_service = get_gcal_service(credentials)
  app.logger.debug("Returned from get_gcal_service")

  if len(Calendars_checked) != 0:
    for cal in Calendars_checked:
      if Calendars_checked[cal]:
        worker_on(gcal_service)
        return render_template('index.html')
  else:
    flask.flash("Checking all the calendar.")
    worker_on(gcal_service)
  
  return render_template('index.html')

#####
#
#  Option setting:  Buttons or forms that add some
#     information into session state.  Don't do the
#     computation here; use of the information might
#     depend on what other information we have.
#   Setting an option sends us back to the main display
#      page, where we may put the new information to use.
#
#####


@app.route('/setrange', methods=['POST'])
def setrange():
  """
  User chose a date range with the bootstrap daterange
  widget.
  """
  app.logger.debug("Entering setrange")
  daterange = request.form.get('daterange')
  flask.session['daterange'] = daterange
  daterange_parts = daterange.split()

  begin_date = daterange_parts[0] + " " + flask.session['begin_time']
  end_date = daterange_parts[2] + " " + flask.session['end_time']

  flask.session['begin_date'] = interpret_date(begin_date)
  flask.session['end_date'] = interpret_date(end_date)
  duration = flask.session.get('duration')
  if duration:
    Set_range = model.eventrange(flask.session['begin_date'], flask.session['end_date'], duration)
  else:
    Set_range = model.eventrange(flask.session['begin_date'], flask.session['end_date'])

  app.logger.debug("Setrange parsed {} - {}  dates as {} - {}".format(
      begin_date, end_date,
      flask.session['begin_date'], flask.session['end_date']))

  return flask.redirect(flask.url_for("choose"))

####
#
#   Initialize session variables
#
####


def init_session_values():
  """
  Start with some reasonable defaults for date and time ranges.
  Note this must be run in app context ... can't call from main. 
  """
  # Default date span = tomorrow to 1 week from now
  # We really should be using tz from browser
  now = arrow.now('local').floor('day')

  # Default time span (hh : min) ~ (hh + 2 : min)
  flask.session["begin_time"] = now.format("HH:mm")
  flask.session["end_time"] = now.shift(hours=2).format("HH:mm")

  tomorrow = now.replace(days=+1)
  nextweek = now.replace(days=+7)
  flask.session["begin_date"] = tomorrow.isoformat()
  flask.session["end_date"] = nextweek.isoformat()
  flask.session["daterange"] = "{} - {}".format(
      tomorrow.format("MM/DD/YYYY"),
      nextweek.format("MM/DD/YYYY"))


def interpret_date(text):
  """
  Convert text of date to ISO format used internally,
  with local timezone
  """
  try:
    as_arrow = arrow.get(text, "MM/DD/YYYY HH:mm").replace(
        tzinfo=tz.tzlocal())
  except:
    flask.flash("Date '{}' didn't fit expected format 12/31/2001")
    raise
  return as_arrow.isoformat()


def next_day(isotext):
  """
  ISO date + 1 day (used in query to Google calendar)
  """
  as_arrow = arrow.get(isotext)
  return as_arrow.replace(days=+1).isoformat()

####
#
#  Functions (NOT pages) that return some information
#
####


def get_busy(service, calendars):
  Set_range = model.eventrange(
      flask.session['begin_date'], flask.session['end_date'])

  items = []
  keys = []

  body = {
      "timeMin": flask.session["begin_date"],
      "timeMax": flask.session["end_date"],
  }

  for calendar in calendars:
    if calendar['selected']:
      items.append({"id": calendar['id']})
      keys.append(calendar['id'])

  body["items"] = items

  app.logger.debug("Body is like " + str(body))

  busy_list = service.freebusy().query(body=body).execute()["calendars"]

  results = []
  for key in keys:
    for chunk in busy_list[key]['busy']:
      tmp_event = model.calendar_event(chunk['start'], chunk['end'])
      if tmp_event.compare_to(Set_range) == model.event_compare_result.within:
        Set_range.blockage.append(tmp_event)
    results.append(busy_list[key]['busy'])

  Set_range.subtract_blockage()
  flask.flash(str(Set_range))
  app.logger.info("%s" % str(Set_range))
  return results


def list_calendars(service):
  """
  Given a google 'service' object, return a list of
  calendars.  Each calendar is represented by a dict.
  The returned list is sorted to have
  the primary calendar first, and selected (that is, displayed in
  Google Calendars web app) calendars before unselected calendars.
  """
  app.logger.debug("Entering list_calendars")
  calendar_list = service.calendarList().list().execute()["items"]
  result = []
  for cal in calendar_list:
    kind = cal["kind"]
    id = cal["id"]
    if "description" in cal:
      desc = cal["description"]
    else:
      desc = "(no description)"
    summary = cal["summary"]
    Cal_id_2_summary[id] = summary
    selected = False
    # Optional binary attributes with False as default
    if len(Calendars_checked) == 0 or Calendars_checked[id]:
      app.logger.debug("Calendars_checked " + str(Calendars_checked))
      selected = True
    primary = ("primary" in cal) and cal["primary"]

    result.append(
        {"kind": kind,
         "id": id,
         "summary": summary,
         "selected": selected,
         "primary": primary
         })
    app.logger.info(str(result))
  return sorted(result, key=cal_sort_key)


def cal_sort_key(cal):
  """
  Sort key for the list of calendars:  primary calendar first,
  then other selected calendars, then unselected calendars.
  (" " sorts before "X", and tuples are compared piecewise)
  """
  if cal["selected"]:
    selected_key = " "
  else:
    selected_key = "X"
  if cal["primary"]:
    primary_key = " "
  else:
    primary_key = "X"
  return (primary_key, selected_key, cal["summary"])


#################
#
# Functions used within the templates
#
#################

@app.template_filter('fmtdate')
def format_arrow_date(date):
  try:
    normal = arrow.get(date)
    return normal.format("ddd MM/DD/YYYY")
  except:
    return "(bad date)"


@app.template_filter('fmttime')
def format_arrow_time(time):
  try:
    normal = arrow.get(time)
    return normal.format("HH:mm")
  except:
    return "(bad time)"


@app.route('/_updateTimeRange', methods=['GET', 'POST'])
def _update_time_range():
  app.logger.debug("Got a updating time range request.")
  timeranges = request.get_json()
  begin_time = timeranges['hour1'] + ':' + timeranges['min1']
  end_time = timeranges['hour2'] + ':' + timeranges['min2']

  flask.session["begin_time"] = begin_time
  flask.session["end_time"] = end_time
  return flask.jsonify(success=True)

@app.route('/_updateDuration', methods=['GET', 'POST'])
def _update_duration():
  result = request.get_json()['duration']
  if result.isdigit():
    result = ceil(float(result))
    flask.session["duration"] = result
    app.logger.debug("Got a updating duration request for %s mins." % result)
  return flask.jsonify(success=True)


@app.route('/_updateSelected', methods=['GET', 'POST'])
def _update_cal_selected():
  app.logger.debug("Got a updating cal_selected request.")
  target_info = request.get_json()
  app.logger.debug("Target_info is like" + str(target_info))
  for raw_id in target_info:
    true_id = raw_id.strip()
    Calendars_checked[true_id] = target_info[raw_id]
  app.logger.debug("Checked calendars is like" + str(Calendars_checked))
  return flask.jsonify(success=True)

#############

####
#
#  Google calendar authorization:
#      Returns us to the main /choose screen after inserting
#      the calendar_service object in the session state.  May
#      redirect to OAuth server first, and may take multiple
#      trips through the oauth2 callback function.
#
#  Protocol for use ON EACH REQUEST:
#     First, check for valid credentials
#     If we don't have valid credentials
#         Get credentials (jump to the oauth2 protocol)
#         (redirects back to /choose, this time with credentials)
#     If we do have valid credentials
#         Get the service object
#
#  The final result of successful authorization is a 'service'
#  object.  We use a 'service' object to actually retrieve data
#  from the Google services. Service objects are NOT serializable ---
#  we can't stash one in a cookie.  Instead, on each request we
#  get a fresh serivce object from our credentials, which are
#  serializable.
#
#  Note that after authorization we always redirect to /choose;
#  If this is unsatisfactory, we'll need a session variable to use
#  as a 'continuation' or 'return address' to use instead.
#
####


def valid_credentials():
  """
  Returns OAuth2 credentials if we have valid
  credentials in the session.  This is a 'truthy' value.
  Return None if we don't have credentials, or if they
  have expired or are otherwise invalid.  This is a 'falsy' value. 
  """
  if 'credentials' not in flask.session:
    return None

  credentials = client.OAuth2Credentials.from_json(
      flask.session['credentials'])

  if (credentials.invalid or
          credentials.access_token_expired):
    return None
  return credentials


def get_gcal_service(credentials):
  """
  We need a Google calendar 'service' object to obtain
  list of calendars, busy times, etc.  This requires
  authorization. If authorization is already in effect,
  we'll just return with the authorization. Otherwise,
  control flow will be interrupted by authorization, and we'll
  end up redirected back to /choose *without a service object*.
  Then the second call will succeed without additional authorization.
  """
  app.logger.debug("Entering get_gcal_service")
  http_auth = credentials.authorize(httplib2.Http())
  service = discovery.build('calendar', 'v3', http=http_auth)
  app.logger.debug("Returning service")
  return service


@app.route('/oauth2callback')
def oauth2callback():
  """
  The 'flow' has this one place to call back to.  We'll enter here
  more than once as steps in the flow are completed, and need to keep
  track of how far we've gotten. The first time we'll do the first
  step, the second time we'll skip the first step and do the second,
  and so on.
  """
  app.logger.debug("Entering oauth2callback")
  flow = client.flow_from_clientsecrets(
      CLIENT_SECRET_FILE,
      scope=SCOPES,
      redirect_uri=flask.url_for('oauth2callback', _external=True))
  # Note we are *not* redirecting above.  We are noting *where*
  # we will redirect to, which is this function.

  # The *second* time we enter here, it's a callback
  # with 'code' set in the URL parameter.  If we don't
  # see that, it must be the first time through, so we
  # need to do step 1.
  app.logger.debug("Got flow")
  if 'code' not in flask.request.args:
    app.logger.debug("Code not in flask.request.args")
    auth_uri = flow.step1_get_authorize_url()
    return flask.redirect(auth_uri)
    # This will redirect back here, but the second time through
    # we'll have the 'code' parameter set
  else:
    # It's the second time through ... we can tell because
    # we got the 'code' argument in the URL.
    app.logger.debug("Code was in flask.request.args")
    auth_code = flask.request.args.get('code')
    credentials = flow.step2_exchange(auth_code)
    flask.session['credentials'] = credentials.to_json()
    # Now I can build the service and execute the query,
    # but for the moment I'll just log it and go back to
    # the main screen
    app.logger.debug("Got credentials")
    return flask.redirect(flask.url_for('choose'))


if __name__ == "__main__":
  # App is created above so that it will
  # exist whether this is 'main' or not
  # (e.g., if we are running under green unicorn)
  app.run(port=CONFIG.PORT, host="0.0.0.0")
