import csv
from codecs import getwriter
from itertools import zip_longest


def write_mechanical_csv(stream, variables):
    """
    Write complete mechanical series as UTF-8 CSV columns

    Rows retain the original zero based sample index. Shorter columns end in
    blank cells so exporting never truncates a longer series.

    Parameters
    ----------
    stream : binary file
        Writable download buffer or ZIP entry owned by the caller.
    variables : list of dict
        Plot variables containing paths, units, values, and calculation flags.
    """
    headers = ["index"]
    for variable in variables:
        header = variable["key"]
        if variable["unit"]:
            header += f' [{variable["unit"]}]'
        if variable.get("calculated"):
            header += " (calculated)"
        if header.lstrip().startswith(("=", "+", "-", "@")):
            header = "'" + header
        headers.append(header)

    writer = csv.writer(getwriter("utf-8-sig")(stream))
    writer.writerow(headers)
    for index, values in enumerate(zip_longest(*(v["values"] for v in variables), fillvalue="")):
        writer.writerow((index, *values))
