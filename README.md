# Karton Dashboard

![](img/dashboard.png)

A small Flask application for Karton task and queue introspection.

**Author**: CERT.pl

**Maintainers**: msm

## Usage

First of all, make sure you have setup the core system: https://github.com/CERT-Polska/karton

Then install karton-dashboard from PyPi:

```shell
$ pip install karton-dashboard

$ karton-dashboard run -h 127.0.0.1 -p 5000
```

The `karton-dashboard` is just a wrapper on the `flask` program, and it works with any arguments accepted by flask. For example `karton-dashboard --help`, or `karton-dashboard run -h 0.0.0.0 -p 1234`. See [flask documentation](https://flask.palletsprojects.com/en/1.1.x/cli/) for more information.

![Co-financed by the Connecting Europe Facility by of the European Union](https://www.cert.pl/wp-content/uploads/2019/02/en_horizontal_cef_logo-1.png)
