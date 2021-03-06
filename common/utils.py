import re
import datetime
import string
import copy
from config.course import ES_COURSE_INDEX_PREFIX


def formatErrMsg(e, header=""):
    if not header.endswith("_"):
        header += "_"
    errmsg = "{}ERROR-{} STR-<{}> REPR-<{}>".format(header, datetime.datetime.now().isoformat(), str(e), repr(e))
    return errmsg


##
## @brief      A dictionary whose values are lists, with a concat() method that
##             concatenates two Listdict object's values.
##
class Listdict(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def concat(self, other):
        _other = copy.deepcopy(other)
        for key, value in _other.items():
            if key in self:
                self[key] += value
            else:
                self[key] = value


##
## @brief      Eliminates spaces and makes each word in lower case.
##
## @param      s          The input string.
## @param      separator  The separator in the string
##
## @return     A list of strings.
##
def splitString(s, separator=","):
    return [elem.strip().lower() for elem
            in s.split(separator) if elem.strip() != ""]


##
## @brief      Gets the string rid of punctuations.
##
## @param      s     (str)
##
## @return     (str)
##
def eliminatePunc(s):
    return re.sub(r"[%s]" % string.punctuation, " ", s)


def getSearchable(s):
    return splitString(eliminatePunc(s).lower(), " ")


##
## @brief      Checks if there is a None in a list/tuple/set/dict.
##
## @param      thing
##
## @return     bool
##
def containsNone(thing):
    if thing is None:
        return True
    if isinstance(thing, str):
        return False
    if ((isinstance(thing, list) or isinstance(thing, tuple)
        or isinstance(thing, set) or isinstance(thing, dict)) and None in thing):
        return True
    return False


def parse_time(time_string):
    try:
        return datetime.datetime.strptime(time_string, "%I:%M%p").time()
    except:
        pass
    try: 
        return datetime.datetime.strptime(time_string, "%H:%M").time()
    except:
        return None


##
## @brief      Get the mini term.
##
## @return     (int) The current mini if no date is provided.
##
def get_mini(current_date=None):
    if current_date is None:
        current_date = datetime.date.today()
    elif isinstance(current_date, datetime.datetime):
        current_date = current_date.date()
    year = current_date.year
    if datetime.date(year, 8, 20) < current_date <= datetime.date(year, 10, 15):
        return 1
    elif datetime.date(year, 10, 15) < current_date <= datetime.date(year, 12, 31):
        return 2
    elif datetime.date(year, 1, 1) <= current_date <= datetime.date(year, 3, 15):
        return 3
    elif datetime.date(year, 3, 15) < current_date <= datetime.date(year, 5, 15):
        return 4
    elif datetime.date(year, 5, 15) < current_date <= datetime.date(year, 7, 1):
        return 5
    elif datetime.date(year, 7, 1) < current_date <= datetime.date(year, 8, 20):
        return 6
    return 0


def get_current_course_index():
    return get_course_index_from_date(datetime.date.today())


def get_course_index_from_date(date):
    return ES_COURSE_INDEX_PREFIX + get_semester_short_from_date(date)


def get_semester_short_from_date(date):
    mini = get_mini(date)
    if 1 <= mini <= 2:
        semester = "f"
    elif 3 <= mini <= 4:
        semester = "s"
    elif mini == 5:
        semester = "m1"
    else:
        semester = "m2"
    semester = semester + str(date.year)[2:]
    return semester


def get_semester_from_date(date):
    mini = get_mini(date)
    if 1 <= mini <= 2:
        semester = "Fall"
    elif 3 <= mini <= 4:
        semester = "Spring"
    elif mini == 5:
        semester = "Summer One"
    else:
        semester = "Summer Two"
    return semester + ' ' + str(date.year)


##
## @brief      Limits the length of string arguments
##
def word_limit(f):
    limit = 100

    def g(*args, **kwargs):
        new_args = []
        new_kwargs = {}
        for i in range(len(args)):
            arg = args[i]
            if type(arg) == str and len(arg) > limit:
                new_args.append(arg[0:limit])
            else:
                new_args.append(arg)
        for key in kwargs:
            arg = kwargs[key]
            if type(arg) == str and len(arg) > limit:
                new_kwargs[key] = arg[0:limit]
            else:
                new_kwargs[key] = arg
        return f(*new_args, **new_kwargs)
    return g


class _Tests():
    @staticmethod
    def test_parse_time():
        assert(datetime.time(8, 15) == parse_time("8:15am"))
        assert(datetime.time(20, 15) == parse_time("8:15PM"))
        assert(datetime.time(8, 0) == parse_time("8:00"))
        assert(datetime.time(20, 0) == parse_time("20:00"))
