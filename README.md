# ftpsync
Utility to synchronize a project (defined by a tree structure of subdirectories and file specifications) to a FTP server

## Example of project

`
mydir
    *.py
    test
        *
    data
        **
    doc
        *.md
        foo.txt
    afile.foo
`

#### Notes

* Four space indentation mendatory
* A directory is always followed by some specifications
* `*` means all files but not recursively
* `**` means allfile recursively
